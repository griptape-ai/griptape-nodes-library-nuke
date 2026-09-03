"""Projects: which workspace the engine is on, what else is available, and how to switch.

Workflows are registered per workspace and a project decides the workspace, so
NukeListWorkflowsRequest and NukeDescribeWorkflowRequest always answer for whichever
project happens to be current, with no way for a host to see that project or change it.
These four verbs close that gap by narrowing the engine's project surface
(``retained_mode/events/project_events.py``, handled in
``retained_mode/managers/project_manager.py``) the way everything else in this layer is
narrowed: ``ProjectTemplate`` is a pydantic model with dozens of fields,
``ProjectValidationInfo`` and ``ProjectTemplateInfo`` are engine dataclasses, and
``ProjectInfo`` additionally carries parsed macro caches. None of them cross the boundary.
"""

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
    """Fold the engine's loaded and failed template lists into one, the way workflow listing does."""
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
    """Narrow one ProjectTemplateInfo, loaded or failed, to the one shape NukeListProjectsRequest reports.

    The engine builds the two kinds identically except for which fields it bothers to fill
    in: a failed entry (``on_list_project_templates_request``) is constructed as
    ``ProjectTemplateInfo(project_id=str(template_path), validation=validation)`` and
    nothing else, so ``name``, ``project_file_path``, and ``parent_project_id`` are always
    ``None`` on one, and its ``project_id`` is always the stringified path of the file that
    failed to load. That guarantee (true only for a failed entry; a loaded one's id may be a
    real GUID, a legacy canonical path, or the system-defaults sentinel) is what lets a
    failed entry's missing ``file_path`` fall back to its own id instead of to an empty
    string, while a missing ``name`` falls back to an explicit empty string on both kinds
    rather than to the opaque id, which this protocol's own rule says a host must never
    parse, construct, or display.
    """
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
    """Collapse the engine's two independent unavailability signals into one string.

    A failed parse and an engine-version mismatch are unrelated engine mechanisms, but a
    host disabling a menu entry does not need to know which one fired.
    """
    if not info.engine_version_compatible:
        return info.engine_version_reason or f"This project requires engine version {info.required_engine_version}."
    if not info.validation.is_usable():
        return f"The project template is {info.validation.status!s}."
    return ""


@verb(NukeGetCurrentProjectRequest)
def handle_get_current_project(
    request: NukeGetCurrentProjectRequest,  # noqa: ARG001
) -> NukeGetCurrentProjectResultSuccess | NukeGetCurrentProjectResultFailure:
    """Read the engine's current ProjectInfo and flatten it to named primitives."""
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
    """Switch projects, refusing while the engine is executing.

    Reloading libraries under a live run is worse than refusing outright: the very library
    driving the run could be torn down and rebuilt out from under it. Serial with
    NukeExecuteWorkflowRequest for the same reason that verb refuses to start a second run.

    ``workspace_changed`` is computed here rather than read from the engine's own result, by
    comparing ``_current_workspace_dir`` before and after the switch. See that helper for why
    it reads the live workspace rather than the offline resolver. The engine's
    SetCurrentProjectResultSuccess itself carries no field for this; it only ever gains one
    as a side effect of a GUI-facing "should I treat my local model as stale" flag that is
    not documented to mean workspace change specifically and is not safe to depend on here.
    """
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
    """Preview a project's workspace and validation without activating it."""
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
    """Return the current project's id, or empty when the engine reports none is set."""
    current = engine.request(GetCurrentProjectRequest(), GetCurrentProjectResultSuccess)
    if current.value is None:
        return ""
    return str(current.value.project_info.project_id)


def _current_workspace_dir() -> str:
    """Return the workspace directory the engine is actually configured against right now.

    Reads GetWorkspaceRequest, not ResolveProjectWorkspaceRequest: this is the live value a
    caller wants when asking about the project that is current, the same value
    ``ProjectManager._activate_project`` itself compares before and after a switch to decide
    whether to reload the workflow registry. Unlike the resolver, it never answers empty,
    because it names no project id to fail to resolve; it just reads whatever the engine's
    ``config_manager.workspace_path`` is, defaults included.
    """
    workspace = engine.request(GetWorkspaceRequest(), GetWorkspaceResultSuccess)
    if workspace.value is None:
        return ""
    return workspace.value.workspace_path


def _resolve_workspace_dir(project_id: str) -> str:
    """Return the workspace directory a project id would resolve to if activated, or empty when it resolves to none.

    The offline previewer: used only by NukeDescribeProjectRequest, for a project that is
    not current, where there is no live workspace to read and a resolved guess is the whole
    point. Answers ``None`` (narrowed here to empty) for any id with no readable project file
    on disk, which includes the system-defaults sentinel, so it must never be used for the
    project that is actually current; see ``_current_workspace_dir``.
    """
    resolved = engine.request(
        ResolveProjectWorkspaceRequest(project_id=project_id), ResolveProjectWorkspaceResultSuccess
    )
    if resolved.value is None or resolved.value.workspace_dir is None:
        return ""
    return resolved.value.workspace_dir
