"""Translate a host's absolute path to the path the engine's own OS uses for it."""

from __future__ import annotations

from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import NamedTuple

from griptape_nodes.common.macro_parser import ParsedMacro
from griptape_nodes.common.project_templates import PerPlatformPathMacro, PerPlatformProjectPath, ProjectTemplate
from griptape_nodes.common.project_templates.directory import active_platform_key
from griptape_nodes.retained_mode.events.project_events import (
    GetCurrentProjectRequest,
    GetCurrentProjectResultSuccess,
    GetPathForMacroRequest,
    GetPathForMacroResultSuccess,
)

from nuke_host_api import engine

_PLATFORM_PATH_TYPES: dict[str, type[PurePath]] = {
    "linux": PurePosixPath,
    "darwin": PurePosixPath,
    "windows": PureWindowsPath,
}
_WORKSPACE_DIR = "workspace_dir"


class _ProjectRoot(NamedTuple):
    """A project folder as one OS names it; the root's type carries that OS's path rules."""

    variable: str
    root: PurePath


class _RootMatch(NamedTuple):
    variable: str
    relative_path: PurePath


async def engine_path(host_path: str) -> str:
    """A host may name shared storage by its own OS's mount, so map it through the project's per-platform folders."""
    if not _is_absolute_anywhere(host_path) or _exists_here(host_path):
        return host_path
    current = await engine.request(GetCurrentProjectRequest(), GetCurrentProjectResultSuccess)
    if current.value is None:
        return host_path
    template = current.value.project_info.template

    workspace = await _resolve_variable(_WORKSPACE_DIR)
    roots = _directory_roots(template)
    # {workspace_dir} resolves to the engine's effective workspace, which an override can move away
    # from the folder the project names; matching the project's value would then open the wrong file.
    if workspace is not None and _names_folder(template.workspace_dir, workspace):
        roots.extend(_roots_for(_WORKSPACE_DIR, template.workspace_dir))

    match = _longest_match(host_path, roots)
    if match is None:
        return host_path
    if match.variable == _WORKSPACE_DIR and workspace is not None:
        local_root = workspace
    else:
        local_root = await _resolve_variable(match.variable)
    if local_root is None:
        return host_path
    return str(local_root.joinpath(*match.relative_path.parts))


def _directory_roots(template: ProjectTemplate) -> list[_ProjectRoot]:
    roots: list[_ProjectRoot] = []
    for name, directory in template.directories.items():
        roots.extend(_roots_for(name, directory.path_macro))
    return roots


def _roots_for(variable: str, value: str | PerPlatformPathMacro | PerPlatformProjectPath | None) -> list[_ProjectRoot]:
    roots: list[_ProjectRoot] = []
    for platform_key, path_type in _PLATFORM_PATH_TYPES.items():
        literal = _literal_absolute(_value_for(value, platform_key), path_type)
        if literal is not None:
            roots.append(_ProjectRoot(variable=variable, root=literal))
    return roots


def _names_folder(value: str | PerPlatformProjectPath | None, folder: Path) -> bool:
    platform_key = active_platform_key()
    literal = _literal_absolute(_value_for(value, platform_key), _PLATFORM_PATH_TYPES.get(platform_key, PurePosixPath))
    if literal is None:
        return False
    return Path(literal).resolve() == folder.resolve()


def _value_for(value: str | PerPlatformPathMacro | PerPlatformProjectPath | None, platform_key: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    platform_value = getattr(value, platform_key, None)
    if platform_value is not None:
        return platform_value
    return value.default


def _literal_absolute(value: str | None, path_type: type[PurePath]) -> PurePath | None:
    # `~`, environment variables, and macros describe the machine that wrote them, so they can't be read here.
    if value is None or value.startswith("~") or any(char in value for char in "{$%"):
        return None
    root = path_type(value)
    if not root.is_absolute():
        return None
    return root


def _longest_match(host_path: str, roots: list[_ProjectRoot]) -> _RootMatch | None:
    best_match: _RootMatch | None = None
    best_depth = -1
    for project_root in roots:
        candidate = type(project_root.root)(host_path)
        if not candidate.is_relative_to(project_root.root):
            continue
        depth = len(project_root.root.parts)
        if depth <= best_depth:
            continue
        best_match = _RootMatch(project_root.variable, candidate.relative_to(project_root.root))
        best_depth = depth
    return best_match


async def _resolve_variable(variable: str) -> Path | None:
    resolved = await engine.request(
        GetPathForMacroRequest(parsed_macro=ParsedMacro(f"{{{variable}}}"), variables={}),
        GetPathForMacroResultSuccess,
    )
    if resolved.value is None:
        return None
    return Path(resolved.value.absolute_path)


def _is_absolute_anywhere(path: str) -> bool:
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def _exists_here(path: str) -> bool:
    local_path = Path(path)
    return bool(local_path.anchor) and local_path.exists()
