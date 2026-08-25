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
    GetParameterValueRequest,
    GetParameterValueResultSuccess,
    SetParameterValueRequest,
    SetParameterValueResultFailure,
    SetParameterValueResultSuccess,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    ListAllWorkflowsRequest,
    ListAllWorkflowsResultSuccess,
    RunWorkflowFromRegistryRequest,
    RunWorkflowFromRegistryResultFailure,
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
from nuke_host_api.handlers.execution import _apply_inputs
from nuke_host_api.protocol import ExecutionState, ValueType
from tests.unit.host_api_fakes import SHAPE, execute_responses, use_engine

NOTHING_LOADED = {GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name=None, result_details="ok")}


class TestExecuteWorkflow:
    def test_a_successful_run_calls_the_engine_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, execute_responses())

        result = handle_execute_workflow(
            NukeExecuteWorkflowRequest(workflow_id="wf1", inputs={"Start Flow": {"topic": "hello"}})
        )

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert result.state == ExecutionState.RUNNING
        assert result.applied_inputs == [{"node": "Start Flow", "parameter": "topic"}]
        assert result.rejected_inputs == []

        request_types = [type(request) for request in engine.requests]
        assert request_types.index(RunWorkflowFromRegistryRequest) < request_types.index(SetParameterValueRequest)
        assert request_types.index(SetParameterValueRequest) < request_types.index(StartFlowRequest)

        load_request = next(r for r in engine.requests if isinstance(r, RunWorkflowFromRegistryRequest))
        assert load_request.run_with_clean_slate is True

    def test_refuses_to_start_over_a_run_already_in_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Loading a second graph would discard the first mid-flight.

        With no execution id in the engine's events, a host could not tell which run the
        following notifications belonged to, nor which one a cancel would stop.
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

        result = handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert not any(isinstance(request, RunWorkflowFromRegistryRequest) for request in engine.requests), (
            "must not load a graph over a running one"
        )
        assert not any(isinstance(request, StartFlowRequest) for request in engine.requests)

    def test_an_input_that_is_not_a_declared_port_is_rejected_without_reaching_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The engine would set a parameter on any node in the loaded graph.

        This transport carries no authentication, so a host must not reach past the inputs
        describe_workflow published.
        """
        engine = use_engine(monkeypatch, execute_responses())

        result = handle_execute_workflow(
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
                "reason": "Not a declared input port of this workflow.",
            }
        ]
        touched = {r.node_name for r in engine.requests if isinstance(r, SetParameterValueRequest)}
        assert touched == {"Start Flow"}

    def test_the_preflight_reads_port_identity_without_normalizing_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Normalizing a macro-templated default issues an engine request.

        The input allow-list needs node and parameter names only, so paying for resolution it
        then discards would put avoidable engine round-trips on every execution.
        """

        def explode(*_args: Any, **_kwargs: Any) -> Any:
            msg = "execute must not normalize port defaults; it needs identity only"
            raise AssertionError(msg)

        use_engine(monkeypatch, execute_responses())
        monkeypatch.setattr(shape, "normalize_value", explode)

        result = handle_execute_workflow(
            NukeExecuteWorkflowRequest(workflow_id="wf1", inputs={"Start Flow": {"topic": "hello"}})
        )

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert result.applied_inputs == [{"node": "Start Flow", "parameter": "topic"}]

    def test_short_circuits_when_the_engine_cannot_load_the_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(
            monkeypatch,
            execute_responses(
                {RunWorkflowFromRegistryRequest: RunWorkflowFromRegistryResultFailure(result_details="not found")}
            ),
        )

        result = handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="ghost"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert not any(isinstance(request, SetParameterValueRequest) for request in engine.requests), (
            "must not touch inputs of a workflow it never loaded"
        )
        assert not any(isinstance(request, StartFlowRequest) for request in engine.requests)

    def test_the_engines_own_reason_reaches_the_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A host cannot see the engine's result, so a refusal it never quotes is lost."""
        use_engine(
            monkeypatch,
            execute_responses(
                {RunWorkflowFromRegistryRequest: RunWorkflowFromRegistryResultFailure(result_details="file is missing")}
            ),
        )

        result = handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert "file is missing" in str(result.result_details)

    def test_short_circuits_when_the_loaded_workflow_has_no_top_level_flow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = use_engine(monkeypatch, execute_responses(NOTHING_LOADED))

        result = handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert not any(isinstance(request, StartFlowRequest) for request in engine.requests)

    def test_short_circuits_when_the_engine_refuses_to_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            execute_responses(
                {StartFlowRequest: StartFlowResultFailure(result_details="validation failed", validation_exceptions=[])}
            ),
        )

        result = handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)


class TestApplyInputs:
    def test_applied_and_rejected_inputs_are_tracked_separately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def respond(request: SetParameterValueRequest) -> Any:
            if request.parameter_name == "good":
                return SetParameterValueResultSuccess(finalized_value=1, data_type="int", result_details="ok")
            return SetParameterValueResultFailure(result_details="rejected: wrong type")

        use_engine(monkeypatch, {SetParameterValueRequest: respond})

        applied, rejected = _apply_inputs(
            {"Node A": {"good": 1, "bad": "nope"}}, {("Node A", "good"), ("Node A", "bad")}
        )

        assert applied == [{"node": "Node A", "parameter": "good"}]
        assert rejected == [{"node": "Node A", "parameter": "bad", "reason": "rejected: wrong type"}]

    def test_a_non_dict_parameters_value_is_rejected_without_calling_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = use_engine(monkeypatch, {})

        applied, rejected = _apply_inputs({"Node A": "not a dict"}, {("Node A", "good")})  # type: ignore[arg-type]

        assert applied == []
        assert rejected == [{"node": "Node A", "parameter": "*", "reason": "Expected an object of parameters."}]
        assert engine.requests == []


class TestGetExecutionState:
    def test_a_running_flow_reports_active_and_involved_nodes(self, monkeypatch: pytest.MonkeyPatch) -> None:
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

        result = handle_get_execution_state(NukeGetExecutionStateRequest(include_outputs=False))

        assert isinstance(result, NukeGetExecutionStateResultSuccess)
        assert result.running is True
        assert result.active_nodes == ["N1"]
        assert result.involved_nodes == ["N1", "N2"]
        assert result.workflow_id == "wf1"
        assert result.outputs == {}

    def test_include_outputs_reads_the_declared_output_ports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def respond_to_get_value(request: GetParameterValueRequest) -> Any:
            if request.parameter_name == "was_successful":
                return GetParameterValueResultSuccess(
                    input_types=["bool"], type="bool", output_type="bool", value=True, result_details="ok"
                )
            return GetParameterValueResultSuccess(
                input_types=["AudioUrlArtifact"],
                type="AudioUrlArtifact",
                output_type="AudioUrlArtifact",
                value="http://x/audio.mp3",
                result_details="ok",
            )

        use_engine(
            monkeypatch,
            {
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                GetFlowStateRequest: GetFlowStateResultSuccess(
                    control_nodes=[], resolving_nodes=[], involved_nodes=[], result_details="ok"
                ),
                GetWorkflowContextRequest: GetWorkflowContextSuccess(workflow_name="wf1", result_details="ok"),
                ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(
                    workflows={"wf1": {"workflow_shape": SHAPE}}, result_details="ok"
                ),
                GetParameterValueRequest: respond_to_get_value,
            },
        )

        result = handle_get_execution_state(NukeGetExecutionStateRequest(include_outputs=True))

        assert isinstance(result, NukeGetExecutionStateResultSuccess)
        assert result.outputs["End Flow"]["was_successful"]["value_type"] == ValueType.BOOL
        assert result.outputs["End Flow"]["mixed_audio"]["value_type"] == ValueType.FILE

    def test_fails_when_no_workflow_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, NOTHING_LOADED)

        result = handle_get_execution_state(NukeGetExecutionStateRequest())

        assert isinstance(result, NukeGetExecutionStateResultFailure)
        assert len(engine.requests) == 1, "must not ask the engine for flow state with nothing loaded"


class TestCancelExecution:
    def test_cancellation_is_requested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                CancelFlowRequest: CancelFlowResultSuccess(result_details="cancelled"),
            },
        )

        result = handle_cancel_execution(NukeCancelExecutionRequest())

        assert isinstance(result, NukeCancelExecutionResultSuccess)

    def test_fails_when_no_workflow_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, NOTHING_LOADED)

        result = handle_cancel_execution(NukeCancelExecutionRequest())

        assert isinstance(result, NukeCancelExecutionResultFailure)
        assert not any(isinstance(request, CancelFlowRequest) for request in engine.requests)

    def test_fails_when_the_engine_refuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                CancelFlowRequest: CancelFlowResultFailure(result_details="nothing running"),
            },
        )

        result = handle_cancel_execution(NukeCancelExecutionRequest())

        assert isinstance(result, NukeCancelExecutionResultFailure)
        assert "nothing running" in str(result.result_details)
