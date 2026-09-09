"""Narrow the engine's project API for hosts."""

from __future__ import annotations

from typing import Any

from griptape_nodes.retained_mode.events.config_events import GetWorkspaceRequest, GetWorkspaceResultSuccess
from griptape_nodes.retained_mode.events.project_events import (
    GetCurrentProjectRequest,
    GetCurrentProjectResultSuccess,
    GetProjectTemplateRequest,
    GetProjectTemplateResultSuccess,
    ListProjectTemplatesRequest,
    ListProjectTemplatesResultSuccess,
    ProjectTemplateInfo,
    ResolveProjectWorkspaceRequest,
    ResolveProjectWorkspaceResultSuccess,
    SetCurrentProjectRequest,
    SetCurrentProjectResultSuccess,
)

from nuke_host_api import engine
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.events import (
    NukeDescribeProjectRequest,
    NukeDescribeProjectResultFailure,
    NukeDescribeProjectResultSuccess,
    NukeGetCurrentProjectRequest,
    NukeGetCurrentProjectResultFailure,
    NukeGetCurrentProjectResultSuccess,
    NukeListProjectsRequest,
    NukeListProjectsResultFailure,
    NukeListProjectsResultSuccess,
    NukeSetCurrentProjectRequest,
    NukeSetCurrentProjectResultFailure,
    NukeSetCurrentProjectResultSuccess,
)


@verb(NukeListProjectsRequest)
def handle_list_projects(
    request: NukeListProjectsRequest,
) -> NukeListProjectsResultSuccess | NukeListProjectsResultFailure:
    listed = engine.request(
        ListProjectTemplatesRequest(include_system_builtins=request.include_system_builtins),
        ListProjectTemplatesResultSuccess,
    )
    if listed.value is None:
        return failure(
            NukeListProjectsResultFailure,
            attempted="to list projects for a host",
            because=f"the engine could not read the project registry. {listed.details}",
        )

    current_id = _current_project_id()
    projects = [
        _describe_project(info, current_id=current_id, loaded=True) for info in listed.value.successfully_loaded
    ]
    projects.extend(
        _describe_project(info, current_id=current_id, loaded=False) for info in listed.value.failed_to_load
    )

    return NukeListProjectsResultSuccess(
        projects=projects,
        result_details=f"Listed {len(projects)} project(s) for a host client.",
    )


def _describe_project(info: ProjectTemplateInfo, *, current_id: str, loaded: bool) -> dict[str, Any]:
    """Failed entries use their path as ID and may omit all other identity fields."""
    file_path = info.project_file_path
    if file_path is None and not loaded:
        file_path = info.project_id

    available = loaded and info.validation.is_usable() and info.engine_version_compatible
    unavailable_reason = _unavailable_reason(info)
    if not unavailable_reason and not loaded:
        unavailable_reason = "The project template failed to load."

    return {
        "id": info.project_id,
        "name": info.name or "",
        "description": "",
        "file_path": file_path or "",
        "parent_id": info.parent_project_id or "",
        "current": info.project_id == current_id,
        "available": available,
        "unavailable_reason": unavailable_reason,
    }


def _unavailable_reason(info: ProjectTemplateInfo) -> str:
    if not info.engine_version_compatible:
        return info.engine_version_reason or f"This project requires engine version {info.required_engine_version}."
    if not info.validation.is_usable():
        return f"The project template is {info.validation.status!s}."
    return ""


@verb(NukeGetCurrentProjectRequest)
def handle_get_current_project(
    request: NukeGetCurrentProjectRequest,  # noqa: ARG001
) -> NukeGetCurrentProjectResultSuccess | NukeGetCurrentProjectResultFailure:
    current = engine.request(GetCurrentProjectRequest(), GetCurrentProjectResultSuccess)
    if current.value is None:
        return failure(
            NukeGetCurrentProjectResultFailure,
            attempted="to read the engine's current project",
            because=f"the engine reports none is set. {current.details}",
        )

    info = current.value.project_info
    return NukeGetCurrentProjectResultSuccess(
        id=str(info.project_id),
        name=info.template.name,
        description=info.template.description or "",
        file_path=str(info.project_file_path) if info.project_file_path is not None else "",
        base_dir=str(info.project_base_dir),
        workspace_dir=_current_workspace_dir(),
        validation_status=str(info.validation.status),
        problems=[problem.message for problem in info.validation.problems],
        result_details=f"Current project is '{info.project_id}'.",
    )


@verb(NukeSetCurrentProjectRequest)
def handle_set_current_project(
    request: NukeSetCurrentProjectRequest,
) -> NukeSetCurrentProjectResultSuccess | NukeSetCurrentProjectResultFailure:
    """Refuse switches during execution and compare live workspaces around the switch."""
    attempted = f"to set the current project to '{request.project_id}'"

    if engine.is_running():
        return failure(
            NukeSetCurrentProjectResultFailure,
            attempted=attempted,
            because=(
                "the engine is already executing. Wait for the current run to "
                "finish, or cancel it with NukeCancelExecutionRequest, then retry."
            ),
        )

    before_workspace = _current_workspace_dir()

    switched = engine.request(SetCurrentProjectRequest(project_id=request.project_id), SetCurrentProjectResultSuccess)
    if switched.value is None:
        return failure(
            NukeSetCurrentProjectResultFailure,
            attempted=attempted,
            because=f"the engine refused. {switched.details}",
        )

    current_id = _current_project_id()
    after_workspace = _current_workspace_dir()

    return NukeSetCurrentProjectResultSuccess(
        project_id=current_id,
        workspace_changed=before_workspace != after_workspace,
        result_details=switched.details,
    )


@verb(NukeDescribeProjectRequest)
def handle_describe_project(
    request: NukeDescribeProjectRequest,
) -> NukeDescribeProjectResultSuccess | NukeDescribeProjectResultFailure:
    attempted = f"to describe project '{request.project_id}'"

    template = engine.request(GetProjectTemplateRequest(project_id=request.project_id), GetProjectTemplateResultSuccess)
    if template.value is None:
        return failure(
            NukeDescribeProjectResultFailure,
            attempted=attempted,
            because=f"no template is cached for that id. {template.details}",
            project_id=request.project_id,
        )

    return NukeDescribeProjectResultSuccess(
        project_id=request.project_id,
        name=template.value.template.name,
        description=template.value.template.description or "",
        workspace_dir=_resolve_workspace_dir(request.project_id),
        validation_status=str(template.value.validation.status),
        problems=[problem.message for problem in template.value.validation.problems],
        result_details=f"Described project '{request.project_id}' for a host client.",
    )


def _current_project_id() -> str:
    current = engine.request(GetCurrentProjectRequest(), GetCurrentProjectResultSuccess)
    if current.value is None:
        return ""
    return str(current.value.project_info.project_id)


def _current_workspace_dir() -> str:
    """Read live workspace configuration because project resolution can be empty for system defaults."""
    workspace = engine.request(GetWorkspaceRequest(), GetWorkspaceResultSuccess)
    if workspace.value is None:
        return ""
    return workspace.value.workspace_path


def _resolve_workspace_dir(project_id: str) -> str:
    """Preview a project's workspace; unreadable files and system defaults resolve to empty."""
    resolved = engine.request(
        ResolveProjectWorkspaceRequest(project_id=project_id), ResolveProjectWorkspaceResultSuccess
    )
    if resolved.value is None or resolved.value.workspace_dir is None:
        return ""
    return resolved.value.workspace_dir
