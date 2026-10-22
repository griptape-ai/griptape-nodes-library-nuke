"""Resolution of the Nuke Script node's Script Path into a concrete file path."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import NamedTuple

from griptape_nodes.common.macro_parser import MacroSyntaxError, ParsedMacro
from griptape_nodes.retained_mode.events.library_events import (
    GetLibrarySourceInfoRequest,
    GetLibrarySourceInfoResultSuccess,
)
from griptape_nodes.retained_mode.events.project_events import (
    GetPathForMacroRequest,
    GetPathForMacroResultFailure,
    GetPathForMacroResultSuccess,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from publish_gizmo.output_paths import absolutize, macro_failure_reason, normalize_for_nuke


class ScriptPathResolution(NamedTuple):
    """Where the Script Path points, or why the text could not be turned into one."""

    # None is the whole signal that resolution failed; there is no half-resolved path
    # worth handing to os.path.exists.
    path: str | None
    # The parameter text exactly as it was stored, so callers can quote it back.
    raw_text: str
    failure_reason: str | None
    missing_variables: tuple[str, ...]


def resolve_script_path(
    raw: str | None,
    *,
    anchor_dir: str | Callable[[], str | None] | None = None,
    library_dir: str | Callable[[], str | None] | None = None,
) -> ScriptPathResolution:
    """Resolve Script Path text, expanding project macros and anchoring relative paths."""
    text = (raw or "").strip()
    if not text:
        return ScriptPathResolution(path=None, raw_text="", failure_reason=None, missing_variables=())

    resolved = text
    if "{library_dir}" in resolved and library_dir is not None:
        # Not a real engine macro: the engine has no notion of "the library this node
        # came from", so it is substituted here before the rest reaches ParsedMacro.
        base = library_dir() if callable(library_dir) else library_dir
        if base:
            resolved = resolved.replace("{library_dir}", base)

    if "{" in resolved:
        # A macro that cannot be read is reported rather than passed through, so the node
        # never stats a literal "{workspace_dir}/..." directory and blames a missing file.
        try:
            parsed_macro = ParsedMacro(resolved)
        except MacroSyntaxError as e:
            return ScriptPathResolution(path=None, raw_text=text, failure_reason=str(e), missing_variables=())

        result = GriptapeNodes.handle_request(GetPathForMacroRequest(parsed_macro=parsed_macro, variables={}))
        if not isinstance(result, GetPathForMacroResultSuccess):
            missing = result.missing_variables if isinstance(result, GetPathForMacroResultFailure) else None
            return ScriptPathResolution(
                path=None,
                raw_text=text,
                failure_reason=macro_failure_reason(result),
                missing_variables=tuple(sorted(missing or ())),
            )
        # Not absolute_path: the engine anchors that on the workspace, not the workflow.
        resolved = str(result.resolved_path)

    if not os.path.isabs(os.path.expanduser(resolved)) and anchor_dir is not None:
        # Relative text would otherwise be resolved against the engine's own working
        # directory, which is a temp dir unrelated to the workflow.
        base = anchor_dir() if callable(anchor_dir) else anchor_dir
        if base:
            return ScriptPathResolution(
                path=absolutize(resolved, base), raw_text=text, failure_reason=None, missing_variables=()
            )

    return ScriptPathResolution(
        path=normalize_for_nuke(os.path.expanduser(resolved)),
        raw_text=text,
        failure_reason=None,
        missing_variables=(),
    )


def describe_failure(resolution: ScriptPathResolution) -> str:
    """Phrase a failed resolution for a node message or validation error."""
    if resolution.failure_reason is None:
        # Name the path actually searched, not the template: quoting "{workspace_dir}/x.nk"
        # back at the user is the confusing message #153 was about.
        if resolution.path is not None:
            return f"Script not found: {resolution.path}"
        return "script_path is not set"
    if resolution.missing_variables:
        names = ", ".join(resolution.missing_variables)
        return f"Could not resolve Script Path {resolution.raw_text!r}: unknown variable(s) {names}"
    return f"Could not resolve Script Path {resolution.raw_text!r}: {resolution.failure_reason}"


def workflow_anchor_dir() -> str | None:
    """Return the current workflow's directory, which relative Script Paths anchor to."""
    parsed = ParsedMacro("{workflow_dir}")
    result = GriptapeNodes.handle_request(GetPathForMacroRequest(parsed_macro=parsed, variables={}))
    if not isinstance(result, GetPathForMacroResultSuccess):
        # An unsaved workflow has no directory yet; relative paths simply stay relative.
        return None
    return str(result.resolved_path)


def library_dir(node_type: str) -> str | None:
    """Return the folder of the library that provides node_type, for anchoring shipped-template paths."""
    library_name = GriptapeNodes.LibraryManager().catalog.get_library_name_for_node_type(node_type)
    if library_name is None:
        return None
    result = GriptapeNodes.handle_request(GetLibrarySourceInfoRequest(library=library_name))
    if not isinstance(result, GetLibrarySourceInfoResultSuccess):
        return None
    return result.library_directory
