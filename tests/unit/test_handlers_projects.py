"""Tests for the project verbs: list, current, switch, describe."""

from __future__ import annotations

from pathlib import Path

import pytest
from griptape_nodes.common.project_templates.default_project_template import default_template_for_version
from griptape_nodes.common.project_templates.project import ProjectTemplate
from griptape_nodes.common.project_templates.validation import (
    ProjectValidationInfo,
    ProjectValidationProblem,
    ProjectValidationProblemSeverity,
    ProjectValidationStatus,
)
from griptape_nodes.retained_mode.events.base_events import ResultPayloadFailure
from griptape_nodes.retained_mode.events.config_events import GetWorkspaceRequest, GetWorkspaceResultSuccess
from griptape_nodes.retained_mode.events.execution_events import GetFlowStateRequest, GetFlowStateResultSuccess
from griptape_nodes.retained_mode.events.flow_events import GetTopLevelFlowRequest, GetTopLevelFlowResultSuccess
from griptape_nodes.retained_mode.events.project_events import (
    GetCurrentProjectRequest,
    GetCurrentProjectResultFailure,
    GetCurrentProjectResultSuccess,
    GetProjectTemplateRequest,
    GetProjectTemplateResultFailure,
    GetProjectTemplateResultSuccess,
    ListProjectTemplatesRequest,
    ListProjectTemplatesResultSuccess,
    ProjectTemplateInfo,
    ResolveProjectWorkspaceRequest,
    ResolveProjectWorkspaceResultSuccess,
    SetCurrentProjectRequest,
    SetCurrentProjectResultFailure,
    SetCurrentProjectResultSuccess,
)
from griptape_nodes.retained_mode.managers.project_manager import ProjectInfo

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
from nuke_host_api.handlers import (
    handle_describe_project,
    handle_get_current_project,
    handle_list_projects,
    handle_set_current_project,
)
from tests.unit.host_api_fakes import use_engine


def _template(name: str = "My Project", description: str = "a project") -> ProjectTemplate:
    template = default_template_for_version("1.0.0")
    template.name = name
    template.description = description
    return template


def _validation(
    status: ProjectValidationStatus = ProjectValidationStatus.GOOD, problems: list[str] | None = None
) -> ProjectValidationInfo:
    return ProjectValidationInfo(
        status=status,
        problems=[
            ProjectValidationProblem(
                line_number=None, field_path="x", message=message, severity=ProjectValidationProblemSeverity.ERROR
            )
            for message in (problems or [])
        ],
    )


def _project_info(
    project_id: str = "proj-1",
    *,
    file_path: Path | None = None,
    base_dir: Path = Path("/workspace/proj-1"),
    template: ProjectTemplate | None = None,
    validation: ProjectValidationInfo | None = None,
) -> ProjectInfo:
    return ProjectInfo(
        project_id=project_id,
        project_file_path=file_path,
        project_base_dir=base_dir,
        template=template or _template(),
        validation=validation or _validation(),
        parsed_situation_schemas={},
        parsed_directory_schemas={},
    )


def _resolve_workspace(workspace_dir: str | None) -> dict[type, object]:
    return {
        ResolveProjectWorkspaceRequest: ResolveProjectWorkspaceResultSuccess(
            workspace_dir=workspace_dir, result_details="resolved"
        )
    }


def _workspace(workspace_path: str) -> dict[type, object]:
    """The engine's one live workspace, for the two verbs that read the active project rather than preview one."""
    return {GetWorkspaceRequest: GetWorkspaceResultSuccess(workspace_path=workspace_path, result_details="ok")}


def _nothing_running() -> dict[type, object]:
    """Short-circuits ``is_running()`` on the ``flow_name is None`` branch, with no flow-state request to fake."""
    return {GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name=None, result_details="none loaded")}


def _current(info: ProjectInfo | None) -> dict[type, object]:
    if info is None:
        return {GetCurrentProjectRequest: GetCurrentProjectResultFailure(result_details="no current project")}
    return {
        GetCurrentProjectRequest: GetCurrentProjectResultSuccess(
            project_info=info, result_details=f"current is {info.project_id}"
        )
    }


class TestListProjects:
    def test_folds_loaded_and_failed_templates_into_one_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        loaded = ProjectTemplateInfo(
            project_id="proj-1", validation=_validation(), name="Proj One", engine_version_compatible=True
        )
        # Matches the engine's own construction of a failed entry exactly
        # (on_list_project_templates_request: ProjectTemplateInfo(project_id=str(template_path),
        # validation=validation), nothing else) rather than a name a failed entry never has.
        failed = ProjectTemplateInfo(project_id="proj-2", validation=_validation(ProjectValidationStatus.UNUSABLE))
        responses = {
            ListProjectTemplatesRequest: ListProjectTemplatesResultSuccess(
                successfully_loaded=[loaded], failed_to_load=[failed], result_details="ok"
            ),
            **_current(_project_info("proj-1")),
        }
        use_engine(monkeypatch, responses)

        result = handle_list_projects(NukeListProjectsRequest())

        assert isinstance(result, NukeListProjectsResultSuccess)
        by_id = {project["id"]: project for project in result.projects}
        assert by_id["proj-1"]["available"] is True
        assert by_id["proj-1"]["current"] is True
        assert by_id["proj-2"]["available"] is False
        assert by_id["proj-2"]["current"] is False
        assert by_id["proj-2"]["unavailable_reason"]

    def test_a_failed_entrys_id_is_reused_as_its_file_path_but_never_as_its_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed entry's id is the stringified path that failed to load; a host must never display it as a name."""
        failed = ProjectTemplateInfo(
            project_id="/projects/broken/griptape-nodes-project.yml",
            validation=_validation(ProjectValidationStatus.MISSING),
        )
        responses = {
            ListProjectTemplatesRequest: ListProjectTemplatesResultSuccess(
                successfully_loaded=[], failed_to_load=[failed], result_details="ok"
            ),
            **_current(None),
        }
        use_engine(monkeypatch, responses)

        result = handle_list_projects(NukeListProjectsRequest())

        assert isinstance(result, NukeListProjectsResultSuccess)
        entry = result.projects[0]
        assert entry["name"] == ""
        assert entry["file_path"] == "/projects/broken/griptape-nodes-project.yml"

    def test_an_engine_incompatible_project_is_unavailable_with_a_reason_a_host_can_show(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loaded = ProjectTemplateInfo(
            project_id="proj-1",
            validation=_validation(),
            name="Proj One",
            engine_version_compatible=False,
            required_engine_version=">=99.0.0",
            engine_version_reason="This engine is too old.",
        )
        responses = {
            ListProjectTemplatesRequest: ListProjectTemplatesResultSuccess(
                successfully_loaded=[loaded], failed_to_load=[], result_details="ok"
            ),
            **_current(None),
        }
        use_engine(monkeypatch, responses)

        result = handle_list_projects(NukeListProjectsRequest())

        assert isinstance(result, NukeListProjectsResultSuccess)
        assert result.projects[0]["available"] is False
        assert result.projects[0]["unavailable_reason"] == "This engine is too old."

    def test_a_failed_to_load_template_reports_unavailable_even_with_no_engine_incompatibility(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failed = ProjectTemplateInfo(project_id="proj-2", validation=_validation(ProjectValidationStatus.MISSING))
        responses = {
            ListProjectTemplatesRequest: ListProjectTemplatesResultSuccess(
                successfully_loaded=[], failed_to_load=[failed], result_details="ok"
            ),
            **_current(None),
        }
        use_engine(monkeypatch, responses)

        result = handle_list_projects(NukeListProjectsRequest())

        assert isinstance(result, NukeListProjectsResultSuccess)
        assert result.projects[0]["available"] is False
        assert result.projects[0]["unavailable_reason"]

    def test_an_unreadable_registry_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # ListProjectTemplatesRequest has no engine-level failure result: its handler never
        # refuses. The only way this layer sees a failure is the app's own catch-all, an
        # unhandled exception turned into a bare ResultPayloadFailure.
        use_engine(monkeypatch, {ListProjectTemplatesRequest: ResultPayloadFailure(result_details="no")})

        result = handle_list_projects(NukeListProjectsRequest())

        assert isinstance(result, NukeListProjectsResultFailure)


class TestGetCurrentProject:
    def test_flattens_project_info_to_named_primitives(self, monkeypatch: pytest.MonkeyPatch) -> None:
        info = _project_info(
            "proj-1",
            file_path=Path("/projects/proj-1/griptape-nodes-project.yml"),
            base_dir=Path("/projects/proj-1"),
            template=_template("Proj One", "a description"),
            validation=_validation(ProjectValidationStatus.FLAWED, problems=["something is off"]),
        )
        responses = {**_current(info), **_workspace("/workspace/proj-1")}
        use_engine(monkeypatch, responses)

        result = handle_get_current_project(NukeGetCurrentProjectRequest())

        assert isinstance(result, NukeGetCurrentProjectResultSuccess)
        assert result.id == "proj-1"
        assert result.name == "Proj One"
        assert result.description == "a description"
        assert result.file_path == "/projects/proj-1/griptape-nodes-project.yml"
        assert result.base_dir == "/projects/proj-1"
        assert result.workspace_dir == "/workspace/proj-1"
        assert result.validation_status == "FLAWED"
        assert result.problems == ["something is off"]

    def test_no_current_project_is_reported_as_a_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, _current(None))

        result = handle_get_current_project(NukeGetCurrentProjectRequest())

        assert isinstance(result, NukeGetCurrentProjectResultFailure)

    def test_a_project_with_no_backing_file_reports_an_empty_file_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The system defaults project has no backing file, but it still has a real, live workspace.

        ``file_path`` is empty because the defaults are not file-backed. ``workspace_dir`` is
        not: GetWorkspaceRequest names no project id to fail to resolve, so it answers with
        whatever workspace the engine is actually configured against, defaults included.
        """
        info = _project_info("<system-defaults>", file_path=None)
        responses = {**_current(info), **_workspace("/workspace/global")}
        use_engine(monkeypatch, responses)

        result = handle_get_current_project(NukeGetCurrentProjectRequest())

        assert isinstance(result, NukeGetCurrentProjectResultSuccess)
        assert result.file_path == ""
        assert result.workspace_dir == "/workspace/global"


class TestSetCurrentProject:
    def test_reports_workspace_changed_when_the_live_workspace_differs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        after_info = _project_info("proj-2")
        workspaces = iter(["/workspace/proj-1", "/workspace/proj-2"])
        fake = use_engine(
            monkeypatch,
            {
                **_nothing_running(),
                GetCurrentProjectRequest: GetCurrentProjectResultSuccess(project_info=after_info, result_details="ok"),
                GetWorkspaceRequest: lambda _req: GetWorkspaceResultSuccess(
                    workspace_path=next(workspaces), result_details="ok"
                ),
                SetCurrentProjectRequest: SetCurrentProjectResultSuccess(result_details="switched"),
            },
        )

        result = handle_set_current_project(NukeSetCurrentProjectRequest(project_id="proj-2"))

        assert isinstance(result, NukeSetCurrentProjectResultSuccess)
        assert result.project_id == "proj-2"
        assert result.workspace_changed is True
        assert any(isinstance(req, SetCurrentProjectRequest) and req.project_id == "proj-2" for req in fake.requests)

    def test_reports_workspace_unchanged_when_the_live_workspace_is_the_same(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        info = _project_info("proj-1")
        use_engine(
            monkeypatch,
            {
                **_nothing_running(),
                GetCurrentProjectRequest: GetCurrentProjectResultSuccess(project_info=info, result_details="ok"),
                **_workspace("/workspace/proj-1"),
                SetCurrentProjectRequest: SetCurrentProjectResultSuccess(result_details="switched"),
            },
        )

        result = handle_set_current_project(NukeSetCurrentProjectRequest(project_id="proj-1"))

        assert isinstance(result, NukeSetCurrentProjectResultSuccess)
        assert result.workspace_changed is False

    def test_a_switch_onto_system_defaults_sharing_the_outgoing_workspace_reports_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression for the offline resolver's blind spot: it cannot resolve the defaults sentinel at all.

        ResolveProjectWorkspaceRequest answers None for any id with no readable project file,
        which includes ``<system-defaults>``, so comparing resolved paths around this switch
        would report a change whenever the defaults share the outgoing project's globally
        configured workspace. GetWorkspaceRequest has no such gap: it names no project id.
        """
        info = _project_info("<system-defaults>", file_path=None)
        use_engine(
            monkeypatch,
            {
                **_nothing_running(),
                GetCurrentProjectRequest: GetCurrentProjectResultSuccess(project_info=info, result_details="ok"),
                **_workspace("/workspace/global"),
                SetCurrentProjectRequest: SetCurrentProjectResultSuccess(result_details="switched"),
            },
        )

        result = handle_set_current_project(NukeSetCurrentProjectRequest(project_id=None))

        assert isinstance(result, NukeSetCurrentProjectResultSuccess)
        assert result.workspace_changed is False

    def test_refuses_while_the_engine_is_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                GetFlowStateRequest: GetFlowStateResultSuccess(
                    control_nodes=["a"], resolving_nodes=[], involved_nodes=["a"], result_details="running"
                ),
            },
        )

        result = handle_set_current_project(NukeSetCurrentProjectRequest(project_id="proj-2"))

        assert isinstance(result, NukeSetCurrentProjectResultFailure)
        assert "already executing" in str(result.result_details)

    def test_an_engine_refusal_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {
                **_nothing_running(),
                **_workspace("/workspace/proj-1"),
                SetCurrentProjectRequest: SetCurrentProjectResultFailure(result_details="engine version mismatch"),
            },
        )

        result = handle_set_current_project(NukeSetCurrentProjectRequest(project_id="proj-2"))

        assert isinstance(result, NukeSetCurrentProjectResultFailure)
        assert "engine version mismatch" in str(result.result_details)


class TestDescribeProject:
    def test_previews_workspace_and_validation_without_activating(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responses = {
            GetProjectTemplateRequest: GetProjectTemplateResultSuccess(
                template=_template("Proj Two", "another project"),
                validation=_validation(ProjectValidationStatus.GOOD),
                result_details="ok",
            ),
            **_resolve_workspace("/workspace/proj-2"),
        }
        use_engine(monkeypatch, responses)

        result = handle_describe_project(NukeDescribeProjectRequest(project_id="proj-2"))

        assert isinstance(result, NukeDescribeProjectResultSuccess)
        assert result.project_id == "proj-2"
        assert result.name == "Proj Two"
        assert result.description == "another project"
        assert result.workspace_dir == "/workspace/proj-2"
        assert result.validation_status == "GOOD"
        assert result.problems == []

    def test_an_unloaded_project_id_is_reported_as_a_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {GetProjectTemplateRequest: GetProjectTemplateResultFailure(result_details="not loaded yet")},
        )

        result = handle_describe_project(NukeDescribeProjectRequest(project_id="ghost"))

        assert isinstance(result, NukeDescribeProjectResultFailure)
        assert result.project_id == "ghost"
