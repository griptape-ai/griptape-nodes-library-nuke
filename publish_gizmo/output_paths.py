"""Output-path resolution shared by the bundled gizmo runner.

This module is copied into the gizmo companion directory at publish time and
imported by ``run_workflow.py``. Keeping the logic here — rather than inline in
the runner, which mutates ``XDG_CONFIG_HOME`` at import time before importing
the engine — lets the unit tests import it normally.

Everything that turns a project directory macro or an engine artifact into a
path Nuke can open lives here, so the runner has exactly one place to consult
and callers can't drift apart on how a relative path is anchored.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from griptape_nodes.common.project_templates import load_project_template_from_yaml
from griptape_nodes.common.project_templates.validation import ProjectValidationInfo, ProjectValidationStatus

if TYPE_CHECKING:
    from griptape_nodes.common.project_templates.project import ProjectTemplate

logger = logging.getLogger(__name__)


def load_project_template(project_yml: Path) -> ProjectTemplate | None:
    """Load a project.yml into a template, or None if it is missing or invalid."""
    if not project_yml.exists():
        return None
    validation_info = ProjectValidationInfo(status=ProjectValidationStatus.GOOD)
    return load_project_template_from_yaml(project_yml.read_text(encoding="utf-8"), validation_info)


def absolutize(value: str, base_dir: str) -> str:
    """Anchor *value* to *base_dir* if relative and normalize to forward slashes.

    Nuke/TCL treats backslashes as escape characters when saving .nk files, which
    silently mangles Windows paths, so every path leaving this module is
    forward-slashed.
    """
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded):
        expanded = os.path.join(base_dir, expanded)
    return os.path.normpath(expanded).replace("\\", "/")


def resolve_output_dir(
    raw: str | None,
    nk_script_dir: str | None,
    companion_dir: str,
    macro_map: dict[str, str] | None = None,
) -> str | None:
    """Resolve the gizmo's Output Directory knob value to an absolute path.

    A relative value is anchored to the Nuke script's directory — the engine
    workspace, and the same base the blank-field case already uses — falling
    back to the companion bundle when the script is unsaved. Anchoring once
    here, rather than letting the engine and Nuke each resolve the same relative
    string against their own working directory, is what keeps the path reported
    back to Nuke openable by the gizmo's internal Read node.

    Project directory macros are expanded against *macro_map* for the same
    reason: left raw, ``{outputs}/renders`` reaches the engine as a
    self-referential ``outputs`` definition, and any macro reaches Nuke as an
    unresolved ``{...}`` literal.
    """
    if not raw:
        return None

    base_dir = nk_script_dir or companion_dir

    if "{" in raw:
        expanded = resolve_macro_path(raw, macro_map or {})
        # Builtins ({workflow_name}, ...) and env-var macros aren't in the map;
        # only the engine can resolve those, so hand it the value untouched.
        if "{" in expanded:
            logger.warning(
                "Output directory %r contains macros this runner cannot resolve; "
                "the path reported back to Nuke may not be openable.",
                raw,
            )
            return raw
        return absolutize(expanded, base_dir)

    return absolutize(raw, base_dir)


def build_macro_map(script_dir: Path, workspace_dir: Path | None = None) -> dict[str, str]:
    """Build a map of macro names to absolute paths from the project.yml.

    The project system stores output values in macro form (e.g. {outputs}/file.jpg).
    This map lets us resolve those macros to real paths that Nuke can open.

    Args:
        script_dir: The companion bundle directory (where project.yml lives).
        workspace_dir: If provided, relative directory macros are resolved
            against this directory instead of *script_dir*.  This is used when
            the Nuke script directory was passed as the workspace so that
            ``{outputs}`` etc. point next to the ``.nk`` file.
    """
    template = load_project_template(script_dir / "project.yml")
    if template is None:
        return {}

    base_dir = str(workspace_dir) if workspace_dir is not None else str(script_dir)

    # Resolve relative macros against base_dir so the companion bundle is portable.
    # Absolute path_macros (e.g. from a legacy publish) keep their location.
    result = {}
    for dir_def in template.directories.values():
        raw = dir_def.path_macro
        value: str | None = raw if isinstance(raw, str) else raw.select() if hasattr(raw, "select") else None
        if not value:
            continue
        result[dir_def.name] = absolutize(value, base_dir)
    return result


def resolve_macro_path(value: str, macro_map: dict[str, str]) -> str:
    """Replace {outputs}, {inputs}, etc. in a path string with their resolved values."""
    if "{" not in value:
        return value

    def _replace(match: re.Match[str]) -> str:
        resolved = macro_map.get(match.group(1))
        return resolved if resolved is not None else match.group(0)

    return re.sub(r"\{([\w-]+)\}", _replace, value)


def serialize_output(output: dict | None, macro_map: dict[str, str]) -> dict[str, str]:
    """Flatten and serialize the workflow output dict for JSON printing.

    The executor returns a nested dict: {node_name: {param_name: value}}.
    We flatten it to {param_name: str(value)} for the gizmo to consume.
    Image artifacts expose a .url or .value attribute that contains the path.
    Macro paths like {outputs}/file.jpg are resolved to absolute paths.
    """
    if not output:
        return {}

    result: dict[str, str] = {}
    for _node_name, params in output.items():
        if not isinstance(params, dict):
            continue
        for param_name, value in params.items():
            if value is None:
                result[param_name] = ""
            elif hasattr(value, "url"):
                result[param_name] = resolve_macro_path(_path_from_file_url(str(value.url)), macro_map)
            elif hasattr(value, "value") and isinstance(value.value, (str, bytes)):
                raw = value.value
                if isinstance(raw, bytes):
                    result[param_name] = f"<binary {len(raw)} bytes>"
                else:
                    result[param_name] = resolve_macro_path(raw, macro_map)
            else:
                result[param_name] = resolve_macro_path(str(value), macro_map)

    return result


def _path_from_file_url(url: str) -> str:
    """Convert a file:// URI to a plain path Nuke can open.

    file:///C:/path (Windows) and file:///unix/path both have three slashes;
    stripping only "file://" leaves "/C:/path" on Windows, which is invalid.
    Strip the third slash only when followed by a drive letter (e.g. /C:/) so
    Unix absolute paths are unchanged.
    """
    if not url.startswith("file://"):
        return url
    url = url[7:]  # -> /C:/... on Windows, /unix/... on Unix
    if len(url) >= 3 and url[0] == "/" and url[1].isalpha() and url[2] == ":":
        url = url[1:]  # -> C:/... on Windows
    return url
