# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.

import contextlib
import logging
import re
import sys
from pathlib import Path

import pydocstyle

from pylsp import hookimpl, lsp

log = logging.getLogger(__name__)

# PyDocstyle is a little verbose in debug message
pydocstyle_logger = logging.getLogger(pydocstyle.utils.__name__)
pydocstyle_logger.setLevel(logging.INFO)

DEFAULT_MATCH_DIR_RE = pydocstyle.config.ConfigurationParser.DEFAULT_MATCH_DIR_RE


@hookimpl
def pylsp_settings():
    # Default pydocstyle to disabled
    return {"plugins": {"pydocstyle": {"enabled": False}}}


@hookimpl
def pylsp_lint(config, workspace, document):
    with workspace.report_progress("lint: pydocstyle"):
        settings = config.plugin_settings("pydocstyle", document_path=document.path)
        log.debug("Got pydocstyle settings: %s", settings)

        # We explicitly pass the path to `pydocstyle`, so it ignores `--match-dir`. But
        # we can match the directory ourselves.
        dir_match_re = re.compile(settings.get("matchDir", DEFAULT_MATCH_DIR_RE) + "$")
        if not dir_match_re.match(Path(document.path).parent.name):
            return []

        args = [document.path]

        def append_if_exists(setting_name, arg_name=None):
            """Append an argument if it exists in `settings`."""
            if setting_name not in settings:
                return False

            if isinstance(settings[setting_name], str):
                value = settings[setting_name]
            else:
                value = ",".join(settings[setting_name])

            args.append(f"--{arg_name or setting_name}={value}")
            return True

        if append_if_exists("convention"):
            append_if_exists("addSelect", "add-select")
            append_if_exists("addIgnore", "add-ignore")
        elif append_if_exists("select"):
            pass
        else:
            append_if_exists("ignore")

        append_if_exists("match")

        log.info("Using pydocstyle args: %s", args)

        conf = pydocstyle.config.ConfigurationParser()
        with _patch_sys_argv(args):
            # TODO(gatesn): We can add more pydocstyle args here from our pylsp config
            conf.parse()

        # Will only yield a single filename, the document path
        diags = []
        for (
            filename,
            checked_codes,
            ignore_decorators,
            property_decorators,
            ignore_self_only_init,
        ) in conf.get_files_to_check():
            errors = pydocstyle.checker.ConventionChecker().check_source(
                document.source,
                filename,
                ignore_decorators=ignore_decorators,
                property_decorators=property_decorators,
                ignore_self_only_init=ignore_self_only_init,
            )

            try:
                for error in errors:
                    if error.code not in checked_codes:
                        continue
                    diags.append(_parse_diagnostic(document, error))
            except pydocstyle.parser.ParseError:
                # In the case we cannot parse the Python file, just continue
                pass

        log.debug("Got pydocstyle errors: %s", diags)
        return diags


def _parse_diagnostic(document, error):
    lineno = error.definition.start - 1
    line = document.lines[0] if document.lines else ""

    start_character = len(line) - len(line.lstrip())
    end_character = len(line)

    return {
        "source": "pydocstyle",
        "code": error.code,
        "message": error.message,
        "severity": lsp.DiagnosticSeverity.Warning,
        "range": {
            "start": {"line": lineno, "character": start_character},
            "end": {"line": lineno, "character": end_character},
        },
    }


@contextlib.contextmanager
def _patch_sys_argv(arguments) -> None:
    old_args = sys.argv

    # Preserve argv[0] since it's the executable
    sys.argv = old_args[0:1] + arguments

    try:
        yield
    finally:
        sys.argv = old_args
