"""Output-path resolution shared by the bundled gizmo runner."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import NamedTuple

from griptape_nodes.common.macro_parser import MacroSyntaxError, ParsedMacro
from griptape_nodes.retained_mode.events.base_events import ResultPayload
from griptape_nodes.retained_mode.events.project_events import (
    GetPathForMacroRequest,
    GetPathForMacroResultFailure,
    GetPathForMacroResultSuccess,
    LoadProjectTemplateRequest,
    LoadProjectTemplateResultSuccess,
    SetCurrentProjectRequest,
    SetCurrentProjectResultSuccess,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

logger = logging.getLogger(__name__)

# Directory name (relative to the .nk script) where workflow outputs land when the
# gizmo's Output Directory knob is left blank. Kept in sync with the copy in
# constants.py.
OUTPUTS_DIR_NAME = "griptape_outputs"


class ProjectActivation(NamedTuple):
    """Whether the bundle's project became the engine's current project, and why not if it didn't."""

    succeeded: bool
    # Kept apart from engine_detail rather than pre-concatenated, so the caller can compose the
    # short cause into its own sentence and trail the engine's raw wording after it.
    failure_reason: str | None
    engine_detail: str | None


class OutputDirResolution(NamedTuple):
    """Where the gizmo's outputs go, or why the Output Directory knob could not be resolved."""

    # None is the whole signal that resolution failed: there is no half-resolved path worth
    # returning, and it narrows for the caller's abort branch.
    path: str | None
    # The knob text exactly as the artist typed it, so the caller can quote it back at them.
    raw_text: str | None
    # GetPathForMacroResultFailure.failure_reason concatenated with .result_details.
    failure_reason: str | None
    missing_variables: tuple[str, ...]


def absolutize(value: str, base_dir: str) -> str:
    """Anchor *value* to *base_dir* if relative and normalize to forward slashes.

    Nuke/TCL treats backslashes as escape characters when saving .nk files, silently
    mangling Windows paths.
    """
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded):
        expanded = os.path.join(base_dir, expanded)
    return os.path.normpath(expanded).replace("\\", "/")


def resolve_output_dir(raw: str | None, nk_script_dir: str | None, companion_dir: str) -> OutputDirResolution:
    """Resolve the gizmo's output directory to an absolute path, or report why the knob could not be read."""
    if not raw:
        return OutputDirResolution(
            path=default_output_dir(nk_script_dir, companion_dir),
            raw_text=None,
            failure_reason=None,
            missing_variables=(),
        )

    # Attempt to parse macros in the knob string, and bail if on syntax errors, rather
    # than write output to a literal `{something}` directory.
    try:
        parsed_macro = ParsedMacro(raw)
    except MacroSyntaxError as e:
        logger.warning("Refusing to run: could not read the Output Directory %r as a macro: %s", raw, e)
        return OutputDirResolution(path=None, raw_text=raw, failure_reason=str(e), missing_variables=())

    result = GriptapeNodes.handle_request(
        GetPathForMacroRequest(parsed_macro=parsed_macro, variables={}, project_id=None)
    )
    if not isinstance(result, GetPathForMacroResultSuccess):
        reason = _macro_failure_reason(result)
        missing = result.missing_variables if isinstance(result, GetPathForMacroResultFailure) else None
        logger.warning("Refusing to run: could not resolve the Output Directory %r: %s", raw, reason)
        return OutputDirResolution(
            path=None, raw_text=raw, failure_reason=reason, missing_variables=tuple(sorted(missing or ()))
        )

    # Anchor relative paths to the .nk script if it is saved, or the bundle root if not.
    base_dir = nk_script_dir or companion_dir

    return OutputDirResolution(
        path=absolutize(str(result.resolved_path), base_dir), raw_text=None, failure_reason=None, missing_variables=()
    )


def default_output_dir(nk_script_dir: str | None, companion_dir: str) -> str:
    """Return where outputs go with the Output Directory knob left blank.

    The default is ``<nk_script_dir or companion_dir>/griptape_outputs``; for an unsaved .nk
    script there is no script directory to sit beside, so it falls back to the bundle root,
    which may be shared or read-only.
    """
    return absolutize(OUTPUTS_DIR_NAME, nk_script_dir or companion_dir)


def _macro_failure_reason(result: ResultPayload) -> str:
    """Describe why the engine refused a macro, keeping the detail that names the offending variable."""
    # failure_reason on its own is a bare enum member ("MACRO_RESOLUTION_ERROR"), which tells an
    # artist nothing; result_details is where the engine explains which name it could not resolve.
    detail = str(result.result_details)
    if not isinstance(result, GetPathForMacroResultFailure):
        return detail
    return f"{result.failure_reason} - {detail}"


def activate_project(project_yml: Path) -> ProjectActivation:
    """Load a project.yml into the engine and make it the current project.

    Activating rather than merely loading means every later macro resolution goes through the
    engine's current project.
    """
    if not project_yml.exists():
        return ProjectActivation(
            succeeded=False,
            failure_reason="that settings file being missing",
            engine_detail=None,
        )

    load_result = GriptapeNodes.handle_request(LoadProjectTemplateRequest(project_path=project_yml))
    if not isinstance(load_result, LoadProjectTemplateResultSuccess):
        return ProjectActivation(
            succeeded=False,
            failure_reason="those settings not being usable",
            engine_detail=str(load_result.result_details),
        )

    activate_result = GriptapeNodes.handle_request(SetCurrentProjectRequest(project_id=load_result.project_id))
    if not isinstance(activate_result, SetCurrentProjectResultSuccess):
        return ProjectActivation(
            succeeded=False,
            failure_reason="those settings being usable but not applied",
            engine_detail=str(activate_result.result_details),
        )

    return ProjectActivation(succeeded=True, failure_reason=None, engine_detail=None)


def serialize_output(output: dict | None) -> dict[str, str]:
    """Flatten the executor's {node: {param: value}} output into {param: str} for the gizmo."""
    if not output:
        return {}

    # Values pass through verbatim: the engine substitutes an output parameter's macros only for
    # str/dict/list values, and NukeEndFlow converts artifact-wrapped macros to str upstream so
    # they qualify. Anything still in braces by here names a variable that could not be resolved.
    result: dict[str, str] = {}
    for _node_name, params in output.items():
        if not isinstance(params, dict):
            continue
        for param_name, value in params.items():
            if value is None:
                result[param_name] = ""
            elif hasattr(value, "url"):
                result[param_name] = _path_from_file_url(str(value.url))
            elif hasattr(value, "value") and isinstance(value.value, (str, bytes)):
                raw = value.value
                result[param_name] = f"<binary {len(raw)} bytes>" if isinstance(raw, bytes) else raw
            else:
                result[param_name] = str(value)

    return result


def _path_from_file_url(url: str) -> str:
    """Convert a file:// URI to a plain path Nuke can open."""
    if not url.startswith("file://"):
        return url
    url = url[7:]  # -> /C:/... on Windows, /unix/... on Unix
    # Both spellings have three slashes, so the third is dropped only before a drive letter; a Unix
    # absolute path needs to keep it.
    if len(url) >= 3 and url[0] == "/" and url[1].isalpha() and url[2] == ":":
        url = url[1:]  # -> C:/... on Windows
    return url
