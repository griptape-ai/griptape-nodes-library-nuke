"""Tests for the execution verbs."""

from __future__ import annotations

from typing import Any

import pytest
from griptape_nodes.retained_mode.events.context_events import (
    GetWorkflowContextRequest,
    GetWorkflowContextSuccess,
)
from griptape_nodes.retained_mode.events.execution_events import (
    CancelFlowRequest,
    CancelFlowResultFailure,
    CancelFlowResultSuccess,
    GetFlowStateRequest,
    GetFlowStateResultSuccess,
    StartFlowRequest,
    StartFlowResultFailure,
)
from griptape_nodes.retained_mode.events.flow_events import (
    GetTopLevelFlowRequest,
    GetTopLevelFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.parameter_events import (
    SetParameterValueRequest,
    SetParameterValueResultFailure,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    ListAllWorkflowsRequest,
    ListAllWorkflowsResultFailure,
    ListAllWorkflowsResultSuccess,
    RunWorkflowFromRegistryRequest,
)

from nuke_host_api import shape
from nuke_host_api.events import (
    NukeCancelExecutionRequest,
    NukeCancelExecutionResultFailure,
    NukeCancelExecutionResultSuccess,
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultFailure,
    NukeExecuteWorkflowResultSuccess,
    NukeGetExecutionStateRequest,
    NukeGetExecutionStateResultFailure,
    NukeGetExecutionStateResultSuccess,
)
from nuke_host_api.handlers import handle_cancel_execution, handle_execute_workflow, handle_get_execution_state
from nuke_host_api.protocol import ExecutionState
from tests.unit.host_api_fakes import WORKFLOW_TABLE, execute_responses, use_engine

NOTHING_LOADED = {GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name=None, result_details="ok")}
NO_WORKFLOW_IN_CONTEXT = {GetWorkflowContextRequest: GetWorkflowContextSuccess(workflow_name="", result_details="ok")}

# The engine keeps the graph an editor user is working on in its registry under an "unsaved:"
# key with no declared shape, and GetWorkflowContextRequest answers with that key.
UNSAVED_GRAPH_LOADED = {
    GetWorkflowContextRequest: GetWorkflowContextSuccess(
        workflow_name="unsaved:9f0c", is_saved=False, result_details="ok"
    ),
    ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(
        workflows={**WORKFLOW_TABLE, "unsaved:9f0c": {"name": "Untitled"}}, result_details="ok"
    ),
}


class TestExecuteWorkflow:
    async def test_a_successful_run_applies_inputs_then_runs_the_loaded_flow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = use_engine(monkeypatch, execute_responses())

        result = await handle_execute_workflow(
            NukeExecuteWorkflowRequest(workflow_id="wf1", inputs={"Start Flow": {"topic": "hello"}})
        )

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        # StartFlowRequest resolves when the flow does, so a reply means the run already ended.
        assert result.state == ExecutionState.COMPLETED
        assert result.applied_inputs == [{"node": "Start Flow", "parameter": "topic"}]
        assert result.rejected_inputs == []

        request_types = [type(request) for request in engine.requests]
        assert request_types.index(SetParameterValueRequest) < request_types.index(StartFlowRequest)

    async def test_loads_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Loading is NukeLoadWorkflowRequest's job, and it clears all object state.

        Doing it here would discard the graph whose inputs a host has been setting, and would
        make every execute pay for a rebuild of a graph that is already loaded.
        """
        engine = use_engine(monkeypatch, execute_responses())

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert not any(isinstance(request, RunWorkflowFromRegistryRequest) for request in engine.requests)

    async def test_no_workflow_id_runs_whatever_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A host driving a graph an editor user loaded has no id to send."""
        use_engine(monkeypatch, execute_responses())

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest())

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert result.workflow_id == "wf1", "the reply must name what actually ran"

    async def test_a_workflow_id_that_is_not_the_loaded_one_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Honouring it would put loading back inside execute; ignoring it would run the wrong graph."""
        engine = use_engine(monkeypatch, execute_responses())

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf2"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert "wf1" in str(result.result_details) and "wf2" in str(result.result_details)
        assert not any(isinstance(request, StartFlowRequest) for request in engine.requests)
        assert not any(isinstance(request, SetParameterValueRequest) for request in engine.requests)

    async def test_fails_when_nothing_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, execute_responses(NO_WORKFLOW_IN_CONTEXT))

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert "NukeLoadWorkflowRequest" in str(result.result_details), "tell a host what to do next"
        assert not any(isinstance(request, StartFlowRequest) for request in engine.requests)

    async def test_refuses_to_start_over_a_run_already_in_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no execution id in the engine's events, a host could not tell two runs apart.

        It could not say which run the notifications that followed belonged to, nor which one a
        cancel would stop.
        """
        engine = use_engine(
            monkeypatch,
            execute_responses(
                {
                    GetFlowStateRequest: GetFlowStateResultSuccess(
                        control_nodes=["C1"], resolving_nodes=["N1"], involved_nodes=["N1"], result_details="busy"
                    )
                }
            ),
        )

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert not any(isinstance(request, SetParameterValueRequest) for request in engine.requests), (
            "must not touch inputs of a run it refused to start"
        )
        assert not any(isinstance(request, StartFlowRequest) for request in engine.requests)

    async def test_an_input_that_is_not_a_declared_parameter_is_rejected_without_reaching_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The engine would set a parameter on any node in the loaded graph.

        This transport carries no authentication, so a host must not reach past the inputs
        describe_workflow published.
        """
        engine = use_engine(monkeypatch, execute_responses())

        result = await handle_execute_workflow(
            NukeExecuteWorkflowRequest(
                workflow_id="wf1",
                inputs={"Start Flow": {"topic": "ok"}, "Some Private Node": {"api_key": "stolen"}},
            )
        )

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert result.applied_inputs == [{"node": "Start Flow", "parameter": "topic"}]
        assert result.rejected_inputs == [
            {
                "node": "Some Private Node",
                "parameter": "api_key",
                "reason": "Not a declared input parameter of this workflow.",
            }
        ]
        touched = {r.node_name for r in engine.requests if isinstance(r, SetParameterValueRequest)}
        assert touched == {"Start Flow"}

    async def test_inputs_sent_to_a_graph_that_declares_none_are_refused_not_rejected_one_by_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unsaved editor graph is in the registry with no shape, so nothing could be applied.

        Starting anyway would report success while running the author's values, and every input
        would come back rejected for a reason that reads like the host named the wrong
        parameters.
        """
        engine = use_engine(monkeypatch, execute_responses(UNSAVED_GRAPH_LOADED))

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(inputs={"Start Flow": {"topic": "hello"}}))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert result.workflow_id == "unsaved:9f0c"
        assert "declares no input parameters" in str(result.result_details)
        assert not any(isinstance(request, StartFlowRequest) for request in engine.requests)
        assert not any(isinstance(request, SetParameterValueRequest) for request in engine.requests)

    async def test_an_unreadable_registry_is_a_retryable_refusal_not_a_graph_that_declares_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both produce an empty allow-list, and only one of them is the host's problem to fix.

        Telling a host that a workflow it saved "declares no input parameters" sends it down the
        unsaved-graph recovery path for something a retry fixes.
        """
        engine = use_engine(
            monkeypatch,
            execute_responses({ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="registry down")}),
        )

        result = await handle_execute_workflow(
            NukeExecuteWorkflowRequest(workflow_id="wf1", inputs={"Start Flow": {"topic": "hello"}})
        )

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        details = str(result.result_details)
        assert "could not read the workflow registry" in details
        assert "Retry" in details
        assert "declares no input parameters" not in details, "wf1 does declare one"
        assert "save it and load it by id" not in details
        assert not any(isinstance(request, StartFlowRequest) for request in engine.requests)
        assert not any(isinstance(request, SetParameterValueRequest) for request in engine.requests)

    async def test_an_unreadable_registry_does_not_block_a_run_with_no_inputs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With nothing to check against the allow-list, the registry does not bear on the run."""
        use_engine(
            monkeypatch,
            execute_responses({ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="registry down")}),
        )

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert result.applied_inputs == []

    async def test_a_graph_that_declares_no_inputs_still_runs_when_none_are_sent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Driving a graph an editor user opened is what an empty workflow_id is for."""
        use_engine(monkeypatch, execute_responses(UNSAVED_GRAPH_LOADED))

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest())

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert result.workflow_id == "unsaved:9f0c"
        assert result.applied_inputs == []
        assert result.rejected_inputs == []

    async def test_an_execution_costs_six_engine_requests_plus_one_per_input_it_forwards(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """None of them loads, which is the whole point of the split.

        Only declared pairs are forwarded, so an undeclared one is the rejection that is free.
        """
        engine = use_engine(monkeypatch, execute_responses())

        result = await handle_execute_workflow(
            NukeExecuteWorkflowRequest(
                workflow_id="wf1",
                inputs={"Start Flow": {"topic": "hello"}, "Some Private Node": {"api_key": "stolen"}},
            )
        )

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        forwarded = sum(isinstance(request, SetParameterValueRequest) for request in engine.requests)
        assert forwarded == 1, "the undeclared pair must not have been forwarded"
        assert len(engine.requests) == 6 + forwarded

    async def test_an_input_the_engine_refuses_has_already_cost_a_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A declared pair is forwarded before its outcome is known, so its rejection is not free.

        The count is per input forwarded, not per input applied. Only the allow-list filters for
        free.
        """
        engine = use_engine(
            monkeypatch,
            execute_responses(
                {SetParameterValueRequest: SetParameterValueResultFailure(result_details="knob is read-only")}
            ),
        )

        result = await handle_execute_workflow(
            NukeExecuteWorkflowRequest(workflow_id="wf1", inputs={"Start Flow": {"topic": "hello"}})
        )

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert result.applied_inputs == []
        assert result.rejected_inputs == [{"node": "Start Flow", "parameter": "topic", "reason": "knob is read-only"}]
        assert len(engine.requests) == 7, "six plus the one forwarded input, whatever the engine said about it"

    async def test_a_loaded_id_missing_from_a_readable_registry_is_not_an_unsaved_graph(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale context key over a live registry: the engine can drop an entry without popping it.

        Telling a host to save a workflow that is not unsaved names a cause it cannot act on.
        Worded as NukeGetParameterValuesRequest words the same engine state.
        """
        engine = use_engine(
            monkeypatch,
            execute_responses(
                {
                    ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(
                        workflows={k: v for k, v in WORKFLOW_TABLE.items() if k != "wf1"}, result_details="ok"
                    )
                }
            ),
        )

        result = await handle_execute_workflow(
            NukeExecuteWorkflowRequest(workflow_id="wf1", inputs={"Start Flow": {"topic": "hello"}})
        )

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        details = str(result.result_details)
        assert "no longer in the registry" in details
        assert "unsaved" not in details
        assert not any(isinstance(request, StartFlowRequest) for request in engine.requests)
        assert not any(isinstance(request, SetParameterValueRequest) for request in engine.requests)

    async def test_the_preflight_reads_parameter_identity_without_normalizing_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Normalizing a macro-templated default issues an engine request.

        The input allow-list needs node and parameter names only, so paying for resolution it
        then discards would put avoidable engine round-trips on every execution.
        """

        def explode(*_args: Any, **_kwargs: Any) -> Any:
            msg = "execute must not normalize parameter defaults; it needs identity only"
            raise AssertionError(msg)

        use_engine(monkeypatch, execute_responses())
        monkeypatch.setattr(shape, "normalize_value", explode)

        result = await handle_execute_workflow(
            NukeExecuteWorkflowRequest(workflow_id="wf1", inputs={"Start Flow": {"topic": "hello"}})
        )

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert result.applied_inputs == [{"node": "Start Flow", "parameter": "topic"}]

    async def test_short_circuits_when_the_loaded_workflow_has_no_top_level_flow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = use_engine(monkeypatch, execute_responses(NOTHING_LOADED))

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert not any(isinstance(request, StartFlowRequest) for request in engine.requests)

    async def test_the_engines_own_reason_for_refusing_to_start_reaches_the_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A host cannot see the engine's result, so a refusal it never quotes is lost."""
        use_engine(
            monkeypatch,
            execute_responses(
                {StartFlowRequest: StartFlowResultFailure(result_details="validation failed", validation_exceptions=[])}
            ),
        )

        result = await handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert "validation failed" in str(result.result_details)


class TestGetExecutionState:
    async def test_a_running_flow_reports_active_and_involved_nodes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                GetFlowStateRequest: GetFlowStateResultSuccess(
                    control_nodes=["C1"], resolving_nodes=["N1"], involved_nodes=["N1", "N2"], result_details="ok"
                ),
                GetWorkflowContextRequest: GetWorkflowContextSuccess(workflow_name="wf1", result_details="ok"),
            },
        )

        result = await handle_get_execution_state(NukeGetExecutionStateRequest())

        assert isinstance(result, NukeGetExecutionStateResultSuccess)
        assert result.running is True
        assert result.active_nodes == ["N1"]
        assert result.involved_nodes == ["N1", "N2"]
        assert result.workflow_id == "wf1"

    async def test_fails_when_no_workflow_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, NOTHING_LOADED)

        result = await handle_get_execution_state(NukeGetExecutionStateRequest())

        assert isinstance(result, NukeGetExecutionStateResultFailure)
        assert len(engine.requests) == 1, "must not ask the engine for flow state with nothing loaded"


class TestCancelExecution:
    async def test_cancellation_is_requested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                CancelFlowRequest: CancelFlowResultSuccess(result_details="cancelled"),
            },
        )

        result = await handle_cancel_execution(NukeCancelExecutionRequest())

        assert isinstance(result, NukeCancelExecutionResultSuccess)

    async def test_fails_when_no_workflow_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, NOTHING_LOADED)

        result = await handle_cancel_execution(NukeCancelExecutionRequest())

        assert isinstance(result, NukeCancelExecutionResultFailure)
        assert not any(isinstance(request, CancelFlowRequest) for request in engine.requests)

    async def test_fails_when_the_engine_refuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                CancelFlowRequest: CancelFlowResultFailure(result_details="nothing running"),
            },
        )

        result = await handle_cancel_execution(NukeCancelExecutionRequest())

        assert isinstance(result, NukeCancelExecutionResultFailure)
        assert "nothing running" in str(result.result_details)
