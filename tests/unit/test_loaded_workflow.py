"""Tests for acting on the host's workflow while the engine has others open.

The engine refuses a request that names no workflow once two are open, so every verb must
name the one the host loaded, and loading must leave the editor's other workflows alone.
"""

from __future__ import annotations

from typing import Any

import pytest
from griptape_nodes.retained_mode.events.context_events import (
    CloseWorkflowRequest,
    CloseWorkflowResultFailure,
    GetWorkflowContextRequest,
)
from griptape_nodes.retained_mode.events.execution_events import GetFlowStateRequest, StartFlowRequest
from griptape_nodes.retained_mode.events.parameter_events import GetParameterValueRequest
from griptape_nodes.retained_mode.events.workflow_events import (
    RunWorkflowFromRegistryRequest,
    RunWorkflowFromRegistryResultSuccess,
)

from nuke_host_api import flow_run, loaded_workflow
from nuke_host_api.events import (
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultSuccess,
    NukeGetParameterValuesRequest,
    NukeGetParameterValuesResultSuccess,
    NukeLoadWorkflowRequest,
    NukeLoadWorkflowResultFailure,
    NukeLoadWorkflowResultSuccess,
)
from nuke_host_api.handlers import handle_execute_workflow, handle_get_parameter_values, handle_load_workflow
from tests.unit.host_api_fakes import FakeEngine, execute_responses, load_responses, respond_to_get_value, use_engine


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

        def open_copy(_request: Any) -> RunWorkflowFromRegistryResultSuccess:
            engine.open_workflows.open("copy-1")
            return RunWorkflowFromRegistryResultSuccess(workflow_id="copy-1", result_details="loaded")

        monkeypatch.setitem(engine._responses, RunWorkflowFromRegistryRequest, open_copy)

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert result.workflow_id == "wf1"
        assert loaded_workflow.current() == loaded_workflow.LoadedWorkflow(open_id="copy-1", name="wf1")

    async def test_load_reads_values_from_the_workflow_it_opened(self, engine: FakeEngine) -> None:
        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert set(engine.named_for(GetParameterValueRequest)) == {"wf1-open"}

    async def test_load_closes_the_hosts_previous_workflow_and_leaves_the_editors_open(
        self, engine: FakeEngine
    ) -> None:
        engine.open_workflows.open("previous")
        loaded_workflow.record("previous", "wf0")

        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert _closes(engine) == ["previous"]
        assert set(engine.open_workflows.by_id) == {"editor-tab", "wf1-open"}

    async def test_load_closes_nothing_when_the_host_loaded_nothing(self, engine: FakeEngine) -> None:
        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert _closes(engine) == []

    async def test_a_refused_close_keeps_the_previous_workflow_loaded(
        self, engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine.open_workflows.open("previous")
        loaded_workflow.record("previous", "wf0")
        monkeypatch.setitem(
            engine._responses, CloseWorkflowRequest, CloseWorkflowResultFailure(result_details="still running")
        )

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.engine_state_cleared is False
        assert "still running" in str(result.result_details)
        assert not any(isinstance(r, RunWorkflowFromRegistryRequest) for r in engine.requests)
        assert loaded_workflow.current() == loaded_workflow.LoadedWorkflow(open_id="previous", name="wf0")

    async def test_load_waits_only_on_the_hosts_own_run(self, engine: FakeEngine) -> None:
        """An editor tab's run is another workflow, so it does not block a load."""
        engine.open_workflows.open("previous")
        loaded_workflow.record("previous", "wf0")

        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert engine.named_for(GetFlowStateRequest)[0] == "previous"


class TestVerbs:
    async def test_verbs_name_the_hosts_workflow(self, engine: FakeEngine) -> None:
        engine.open_workflows.open("wf1-open")
        loaded_workflow.record("wf1-open", "wf1")

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(inputs={"Start Flow": {"topic": "x"}}))
        await flow_run._RUN  # type: ignore[misc]

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert result.workflow_id == "wf1"
        assert set(engine.named) == {"wf1-open"}
        assert engine.named_for(StartFlowRequest) == ["wf1-open"]

    async def test_verbs_report_the_hosts_workflow_without_asking_the_engine(self, engine: FakeEngine) -> None:
        """The engine's context for a template copy names the copy, not what the host loaded."""
        engine.open_workflows.open("copy-1")
        loaded_workflow.record("copy-1", "wf1")

        result = await handle_get_parameter_values(NukeGetParameterValuesRequest())

        assert isinstance(result, NukeGetParameterValuesResultSuccess)
        assert result.workflow_id == "wf1"
        assert not any(isinstance(r, GetWorkflowContextRequest) for r in engine.requests)

    async def test_a_workflow_closed_elsewhere_falls_back_to_the_engines_only_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = use_engine(monkeypatch, execute_responses({GetParameterValueRequest: respond_to_get_value}))
        engine.open_workflows.open("editor-tab")
        loaded_workflow.record("closed-in-editor", "wf0")

        result = await handle_get_parameter_values(NukeGetParameterValuesRequest())

        assert isinstance(result, NukeGetParameterValuesResultSuccess)
        assert result.workflow_id == "wf1"
        assert set(engine.named) == {"editor-tab"}

    async def test_with_nothing_loaded_verbs_name_the_workflow_an_editor_opened(self, engine: FakeEngine) -> None:
        """The engine doesn't pick the only open workflow for a request that names none, so the host names it."""
        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(inputs={"Start Flow": {"topic": "x"}}))
        await flow_run._RUN  # type: ignore[misc]

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert set(engine.named) == {"editor-tab"}
        assert engine.named_for(GetWorkflowContextRequest) == ["editor-tab"]

    async def test_with_nothing_loaded_and_several_open_verbs_name_none(self, engine: FakeEngine) -> None:
        engine.open_workflows.open("second-tab")

        await handle_get_parameter_values(NukeGetParameterValuesRequest())

        assert set(engine.named) == {None}


class TestEmittedElsewhere:
    def test_nothing_is_elsewhere_before_the_host_loads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch)
        with engine.bind_workflow(engine.open_workflows.open("editor-tab")):
            assert loaded_workflow.emitted_elsewhere() is False

    def test_another_workflows_work_is_elsewhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch)
        engine.open_workflows.open("wf1-open")
        loaded_workflow.record("wf1-open", "wf1")
        with engine.bind_workflow(engine.open_workflows.open("editor-tab")):
            assert loaded_workflow.emitted_elsewhere() is True

    def test_the_hosts_own_work_is_not_elsewhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch)
        loaded_workflow.record("wf1-open", "wf1")
        with engine.bind_workflow(engine.open_workflows.open("wf1-open")):
            assert loaded_workflow.emitted_elsewhere() is False

    def test_unbound_work_is_not_elsewhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch).open_workflows.open("wf1-open")
        loaded_workflow.record("wf1-open", "wf1")
        assert loaded_workflow.emitted_elsewhere() is False

    def test_nothing_is_elsewhere_once_the_hosts_workflow_closes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verbs fall back to the only open workflow then, so its events are the host's to see."""
        engine = use_engine(monkeypatch)
        loaded_workflow.record("closed-in-editor", "wf0")
        with engine.bind_workflow(engine.open_workflows.open("editor-tab")):
            assert loaded_workflow.emitted_elsewhere() is False
