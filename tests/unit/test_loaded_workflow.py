"""Tests for acting on the host's workflow while the engine has others open.

Load opens the workflow it names, reopening the host's own copy from its file, or takes it as it is
when an editor tab already has it open, and
every verb names that workflow until the next load. With none loaded, verbs report it rather than
act on another workflow.
"""

from __future__ import annotations

from typing import Any

import pytest
from griptape_nodes.retained_mode.events.app_events import OpenWorkflowInfo
from griptape_nodes.retained_mode.events.context_events import (
    CloseWorkflowRequest,
    CloseWorkflowResultFailure,
    GetWorkflowContextRequest,
    OpenWorkflowRequest,
    OpenWorkflowResultFailure,
    OpenWorkflowResultSuccess,
)
from griptape_nodes.retained_mode.events.execution_events import GetFlowStateRequest, StartFlowRequest
from griptape_nodes.retained_mode.events.parameter_events import GetParameterValueRequest

from nuke_host_api import flow_run, loaded_workflow
from nuke_host_api.events import (
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultFailure,
    NukeExecuteWorkflowResultSuccess,
    NukeGetParameterValuesRequest,
    NukeGetParameterValuesResultFailure,
    NukeGetParameterValuesResultSuccess,
    NukeLoadWorkflowRequest,
    NukeLoadWorkflowResultFailure,
    NukeLoadWorkflowResultSuccess,
)
from nuke_host_api.handlers import handle_execute_workflow, handle_get_parameter_values, handle_load_workflow
from tests.unit.host_api_fakes import FakeEngine, execute_responses, load_responses, use_engine


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    """An engine with an editor tab open, which every test expects to survive."""
    fake = use_engine(monkeypatch, {**load_responses(), **execute_responses()})
    fake.open_workflows.open("editor-tab")
    return fake


def _closes(engine: FakeEngine) -> list[str]:
    return [r.workflow_id for r in engine.requests if isinstance(r, CloseWorkflowRequest)]


class TestLoad:
    async def test_load_records_the_open_workflow_under_the_name_the_host_asked_for(
        self, engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A template opens as a copy with its own id, but the host keeps addressing it by name."""

        def open_copy(_request: Any) -> OpenWorkflowResultSuccess:
            engine.open_workflows.open("copy-1")
            info = OpenWorkflowInfo(
                workflow_id="copy-1",
                name="unsaved:copy-1",
                display_name="WF One",
                workflow_file_path=None,
                is_saved=False,
                has_active_flow=True,
            )
            return OpenWorkflowResultSuccess(open_workflow=info, already_open=False, result_details="opened")

        monkeypatch.setitem(engine._responses, OpenWorkflowRequest, open_copy)

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert result.workflow_id == "wf1"
        assert loaded_workflow.current() == loaded_workflow.LoadedWorkflow(
            open_id="copy-1", name="wf1", opened_by_host=True
        )

    async def test_load_reads_values_from_the_workflow_it_opened(self, engine: FakeEngine) -> None:
        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert set(engine.named_for(GetParameterValueRequest)) == {"wf1-open"}

    async def test_load_takes_a_workflow_an_editor_tab_has_open_as_it_is(self, engine: FakeEngine) -> None:
        """Nuke and the editor then act on one graph, unsaved edits included, and Nuke never closes it."""
        engine.open_workflows.open("wf1-open")

        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert loaded_workflow.current() == loaded_workflow.LoadedWorkflow(
            open_id="wf1-open", name="wf1", opened_by_host=False
        )
        assert engine.open_workflows.find("wf1-open") is not None

    async def test_the_next_load_closes_a_workflow_the_host_opened(self, engine: FakeEngine) -> None:
        engine.open_workflows.open("previous")
        loaded_workflow.record("previous", "wf0", opened_by_host=True)

        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert _closes(engine) == ["previous"]
        assert set(engine.open_workflows.by_id) == {"editor-tab", "wf1-open"}

    async def test_the_next_load_leaves_a_workflow_the_host_found_open(self, engine: FakeEngine) -> None:
        loaded_workflow.record("editor-tab", "wf0", opened_by_host=False)

        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert _closes(engine) == []
        assert set(engine.open_workflows.by_id) == {"editor-tab", "wf1-open"}

    async def test_load_closes_nothing_when_the_host_loaded_nothing(self, engine: FakeEngine) -> None:
        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert _closes(engine) == []

    async def test_reloading_a_workflow_the_host_opened_reopens_it_from_its_file(self, engine: FakeEngine) -> None:
        """Closed before the open, so a reload resets values and picks up changes on disk."""
        engine.open_workflows.open("wf1-open")
        loaded_workflow.record("wf1-open", "wf1", opened_by_host=True)

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        kinds = [type(r) for r in engine.requests if isinstance(r, (CloseWorkflowRequest, OpenWorkflowRequest))]
        assert kinds == [CloseWorkflowRequest, OpenWorkflowRequest]
        assert _closes(engine) == ["wf1-open"]
        assert loaded_workflow.current() == loaded_workflow.LoadedWorkflow(
            open_id="wf1-open", name="wf1", opened_by_host=True
        )

    async def test_reloading_a_workflow_an_editor_tab_has_open_keeps_it(self, engine: FakeEngine) -> None:
        """The editor's copy is never closed, so edits made there survive."""
        engine.open_workflows.open("wf1-open")
        loaded_workflow.record("wf1-open", "wf1", opened_by_host=False)

        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert _closes(engine) == []
        assert loaded_workflow.current() == loaded_workflow.LoadedWorkflow(
            open_id="wf1-open", name="wf1", opened_by_host=False
        )

    async def test_a_refused_close_on_reload_refuses_the_load_and_keeps_the_workflow(
        self, engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine.open_workflows.open("wf1-open")
        loaded_workflow.record("wf1-open", "wf1", opened_by_host=True)
        monkeypatch.setitem(
            engine._responses, CloseWorkflowRequest, CloseWorkflowResultFailure(result_details="still running")
        )

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.engine_state_cleared is False
        assert not any(isinstance(r, OpenWorkflowRequest) for r in engine.requests)
        assert loaded_workflow.current() == loaded_workflow.LoadedWorkflow(
            open_id="wf1-open", name="wf1", opened_by_host=True
        )

    async def test_a_failed_reopen_leaves_nothing_loaded_and_says_so(
        self, engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine.open_workflows.open("wf1-open")
        loaded_workflow.record("wf1-open", "wf1", opened_by_host=True)
        monkeypatch.setitem(
            engine._responses, OpenWorkflowRequest, OpenWorkflowResultFailure(result_details="missing library")
        )

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.engine_state_cleared is True
        assert "nothing is loaded now" in str(result.result_details)
        assert loaded_workflow.current() is None

    async def test_a_refused_close_still_loads_the_new_workflow(
        self, engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The new workflow is already open, so the previous one only stays open beside it."""
        engine.open_workflows.open("previous")
        loaded_workflow.record("previous", "wf0", opened_by_host=True)
        monkeypatch.setitem(
            engine._responses, CloseWorkflowRequest, CloseWorkflowResultFailure(result_details="still running")
        )

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert loaded_workflow.current() == loaded_workflow.LoadedWorkflow(
            open_id="wf1-open", name="wf1", opened_by_host=True
        )
        assert "Could not close 'wf0'" in str(result.result_details), "the host must learn it is still open"

    async def test_load_waits_only_on_the_hosts_own_run(self, engine: FakeEngine) -> None:
        """An editor tab's run is another workflow, so it does not block a load."""
        engine.open_workflows.open("previous")
        loaded_workflow.record("previous", "wf0", opened_by_host=True)

        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert engine.named_for(GetFlowStateRequest)[0] == "previous"


class TestVerbs:
    async def test_verbs_name_the_hosts_workflow(self, engine: FakeEngine) -> None:
        engine.open_workflows.open("wf1-open")
        loaded_workflow.record("wf1-open", "wf1", opened_by_host=True)

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(inputs={"Start Flow": {"topic": "x"}}))
        await flow_run._RUN  # type: ignore[misc]

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert result.workflow_id == "wf1"
        assert set(engine.named) == {"wf1-open"}
        assert engine.named_for(StartFlowRequest) == ["wf1-open"]

    async def test_verbs_report_the_hosts_workflow_without_asking_the_engine(self, engine: FakeEngine) -> None:
        """The engine's context for a template copy names the copy, not what the host loaded."""
        engine.open_workflows.open("copy-1")
        loaded_workflow.record("copy-1", "wf1", opened_by_host=True)

        result = await handle_get_parameter_values(NukeGetParameterValuesRequest())

        assert isinstance(result, NukeGetParameterValuesResultSuccess)
        assert result.workflow_id == "wf1"
        assert not any(isinstance(r, GetWorkflowContextRequest) for r in engine.requests)

    async def test_with_nothing_loaded_verbs_leave_an_editors_workflow_alone(self, engine: FakeEngine) -> None:
        """The host acts only on what it loaded, even with one workflow open."""
        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(inputs={"Start Flow": {"topic": "x"}}))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert "no workflow is loaded" in str(result.result_details)
        assert engine.requests == []

    async def test_a_workflow_closed_elsewhere_is_not_loaded_anymore(self, engine: FakeEngine) -> None:
        loaded_workflow.record("closed-in-editor", "wf0", opened_by_host=True)

        result = await handle_get_parameter_values(NukeGetParameterValuesRequest())

        assert isinstance(result, NukeGetParameterValuesResultFailure)
        assert "no workflow is loaded" in str(result.result_details)
        assert engine.requests == []


class TestEmittedElsewhere:
    def test_another_workflows_work_is_elsewhere_before_the_host_loads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch)
        with engine.bind_workflow(engine.open_workflows.open("editor-tab")):
            assert loaded_workflow.emitted_elsewhere() is True

    def test_another_workflows_work_is_elsewhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch)
        engine.open_workflows.open("wf1-open")
        loaded_workflow.record("wf1-open", "wf1", opened_by_host=True)
        with engine.bind_workflow(engine.open_workflows.open("editor-tab")):
            assert loaded_workflow.emitted_elsewhere() is True

    def test_the_hosts_own_work_is_not_elsewhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch)
        loaded_workflow.record("wf1-open", "wf1", opened_by_host=True)
        with engine.bind_workflow(engine.open_workflows.open("wf1-open")):
            assert loaded_workflow.emitted_elsewhere() is False

    def test_unbound_work_is_not_elsewhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch).open_workflows.open("wf1-open")
        loaded_workflow.record("wf1-open", "wf1", opened_by_host=True)
        assert loaded_workflow.emitted_elsewhere() is False

    def test_another_workflows_work_is_elsewhere_once_the_hosts_workflow_closes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verbs report nothing loaded then, so another workflow's events are not the host's."""
        engine = use_engine(monkeypatch)
        loaded_workflow.record("closed-in-editor", "wf0", opened_by_host=True)
        with engine.bind_workflow(engine.open_workflows.open("editor-tab")):
            assert loaded_workflow.emitted_elsewhere() is True
