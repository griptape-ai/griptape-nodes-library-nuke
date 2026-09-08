"""Tests for the bulk parameter-value read verb."""

from __future__ import annotations

from typing import Any

import pytest
from griptape_nodes.retained_mode.events.context_events import (
    GetWorkflowContextRequest,
    GetWorkflowContextSuccess,
)
from griptape_nodes.retained_mode.events.execution_events import (
    GetFlowStateRequest,
    GetFlowStateResultSuccess,
    StartFlowRequest,
)
from griptape_nodes.retained_mode.events.parameter_events import (
    GetParameterValueRequest,
    GetParameterValueResultFailure,
    SetParameterValueRequest,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    ListAllWorkflowsRequest,
    ListAllWorkflowsResultFailure,
    ListAllWorkflowsResultSuccess,
)

from nuke_host_api.events import (
    NukeGetParameterValuesRequest,
    NukeGetParameterValuesResultFailure,
    NukeGetParameterValuesResultSuccess,
    NukeSetParameterValuesRequest,
    NukeSetParameterValuesResultFailure,
    NukeSetParameterValuesResultSuccess,
)
from nuke_host_api.handlers import handle_get_parameter_values, handle_set_parameter_values
from nuke_host_api.protocol import ParameterSection, ValueType
from tests.unit.host_api_fakes import SHAPE, execute_responses, respond_to_get_value, use_engine

NOTHING_LOADED = {GetWorkflowContextRequest: GetWorkflowContextSuccess(workflow_name="", result_details="ok")}

WORKFLOW_LOADED: dict[type, Any] = {
    GetWorkflowContextRequest: GetWorkflowContextSuccess(workflow_name="wf1", result_details="ok"),
    ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(
        workflows={"wf1": {"workflow_shape": SHAPE}}, result_details="ok"
    ),
}


class TestGetParameterValues:
    def test_no_sections_requested_reads_both_sides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: respond_to_get_value})

        result = handle_get_parameter_values(NukeGetParameterValuesRequest())

        assert isinstance(result, NukeGetParameterValuesResultSuccess)
        assert result.workflow_id == "wf1"
        assert set(result.requested_sections) == {ParameterSection.INPUTS, ParameterSection.OUTPUTS}
        assert result.inputs["Start Flow"]["topic"]["value_type"] == ValueType.TEXT
        assert result.outputs["End Flow"]["was_successful"]["value_type"] == ValueType.BOOL
        assert result.outputs["End Flow"]["mixed_audio"]["value_type"] == ValueType.FILE
        # A value the engine genuinely holds as None is not a parameter it would not answer for:
        # it lands in `inputs` as GTNull, not in `unavailable`. See handlers/values.py's
        # third reason for not using GetAllNodeInfoRequest.
        assert result.inputs["Start Flow"]["plate"]["value_type"] == ValueType.NULL
        assert result.unavailable == []

    def test_a_single_section_reads_only_that_side(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: respond_to_get_value})

        result = handle_get_parameter_values(NukeGetParameterValuesRequest(sections=[ParameterSection.INPUTS]))

        assert isinstance(result, NukeGetParameterValuesResultSuccess)
        assert result.requested_sections == [ParameterSection.INPUTS]
        assert result.inputs["Start Flow"]["topic"]["value_type"] == ValueType.TEXT
        assert result.outputs == {}
        read_parameters = {r.parameter_name for r in engine.requests if isinstance(r, GetParameterValueRequest)}
        assert read_parameters == {"topic", "plate"}, "must not read the output side when only inputs was requested"

    def test_an_unknown_section_is_refused_without_reaching_the_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: respond_to_get_value})

        result = handle_get_parameter_values(NukeGetParameterValuesRequest(sections=["sideways"]))

        assert isinstance(result, NukeGetParameterValuesResultFailure)
        assert "sideways" in str(result.result_details)
        assert not any(isinstance(r, GetParameterValueRequest) for r in engine.requests)

    def test_fails_when_no_workflow_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, NOTHING_LOADED)

        result = handle_get_parameter_values(NukeGetParameterValuesRequest())

        assert isinstance(result, NukeGetParameterValuesResultFailure)
        assert not any(isinstance(r, GetParameterValueRequest) for r in engine.requests)

    def test_a_parameter_the_engine_will_not_answer_for_is_reported_not_omitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def respond(request: GetParameterValueRequest) -> Any:
            if request.parameter_name == "topic":
                return GetParameterValueResultFailure(result_details="node was deleted mid-read")
            return respond_to_get_value(request)

        use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: respond})

        result = handle_get_parameter_values(NukeGetParameterValuesRequest(sections=[ParameterSection.INPUTS]))

        assert isinstance(result, NukeGetParameterValuesResultSuccess)
        assert "Start Flow" not in result.inputs or "topic" not in result.inputs.get("Start Flow", {})
        assert result.unavailable == [
            {
                "section": ParameterSection.INPUTS,
                "node": "Start Flow",
                "parameter": "topic",
                "reason": "node was deleted mid-read",
            }
        ]

    def test_control_parameters_are_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: respond_to_get_value})

        result = handle_get_parameter_values(NukeGetParameterValuesRequest())

        assert isinstance(result, NukeGetParameterValuesResultSuccess)
        assert "exec_out" not in result.inputs.get("Start Flow", {})
        assert "exec_in" not in result.outputs.get("End Flow", {})

    def test_values_are_normalized_the_same_shape_as_a_describe_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: respond_to_get_value})

        result = handle_get_parameter_values(NukeGetParameterValuesRequest())

        assert isinstance(result, NukeGetParameterValuesResultSuccess)
        descriptor = result.outputs["End Flow"]["was_successful"]
        assert set(descriptor) == {"value_type", "sources", "colorspace", "engine_type"}


# execute_responses() already sets up an idle flow with "wf1" loaded and its declared shape
# readable, which is exactly the preflight NukeSetParameterValuesRequest shares with
# NukeExecuteWorkflowRequest.
UNSAVED_GRAPH_LOADED: dict[type, Any] = {
    GetWorkflowContextRequest: GetWorkflowContextSuccess(
        workflow_name="unsaved:9f0c", is_saved=False, result_details="ok"
    ),
    ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(
        workflows={"wf1": {"workflow_shape": SHAPE}, "unsaved:9f0c": {"name": "Untitled"}}, result_details="ok"
    ),
}


class TestSetParameterValues:
    def test_a_declared_input_is_applied_without_starting_a_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, execute_responses())

        result = handle_set_parameter_values(NukeSetParameterValuesRequest(inputs={"Start Flow": {"topic": "hello"}}))

        assert isinstance(result, NukeSetParameterValuesResultSuccess)
        assert result.workflow_id == "wf1"
        assert result.applied_inputs == [{"node": "Start Flow", "parameter": "topic"}]
        assert result.rejected_inputs == []
        assert not any(isinstance(r, StartFlowRequest) for r in engine.requests)

    def test_an_empty_request_is_refused_rather_than_answered_as_a_trivial_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = use_engine(monkeypatch, execute_responses())

        result = handle_set_parameter_values(NukeSetParameterValuesRequest())

        assert isinstance(result, NukeSetParameterValuesResultFailure)
        assert "nothing to set" in str(result.result_details)
        assert not any(isinstance(r, SetParameterValueRequest) for r in engine.requests)

    def test_refuses_while_the_engine_is_executing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A value set mid-run cannot be told apart from one that landed in time or too late."""
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

        result = handle_set_parameter_values(NukeSetParameterValuesRequest(inputs={"Start Flow": {"topic": "hello"}}))

        assert isinstance(result, NukeSetParameterValuesResultFailure)
        assert not any(isinstance(r, SetParameterValueRequest) for r in engine.requests)

    def test_fails_when_nothing_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, execute_responses(NOTHING_LOADED))

        result = handle_set_parameter_values(NukeSetParameterValuesRequest(inputs={"Start Flow": {"topic": "hello"}}))

        assert isinstance(result, NukeSetParameterValuesResultFailure)
        assert "NukeLoadWorkflowRequest" in str(result.result_details)
        assert not any(isinstance(r, SetParameterValueRequest) for r in engine.requests)

    def test_a_pair_outside_the_allow_list_is_rejected_not_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, execute_responses())

        result = handle_set_parameter_values(
            NukeSetParameterValuesRequest(
                inputs={"Start Flow": {"topic": "ok"}, "Some Private Node": {"api_key": "stolen"}}
            )
        )

        assert isinstance(result, NukeSetParameterValuesResultSuccess)
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

    def test_values_sent_to_a_graph_that_declares_none_are_refused_not_rejected_one_by_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = use_engine(monkeypatch, execute_responses(UNSAVED_GRAPH_LOADED))

        result = handle_set_parameter_values(NukeSetParameterValuesRequest(inputs={"Start Flow": {"topic": "hello"}}))

        assert isinstance(result, NukeSetParameterValuesResultFailure)
        assert result.workflow_id == "unsaved:9f0c"
        assert "declares no input parameters" in str(result.result_details)
        assert not any(isinstance(r, SetParameterValueRequest) for r in engine.requests)

    def test_an_unreadable_registry_is_a_retryable_refusal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(
            monkeypatch,
            execute_responses({ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="registry down")}),
        )

        result = handle_set_parameter_values(NukeSetParameterValuesRequest(inputs={"Start Flow": {"topic": "hello"}}))

        assert isinstance(result, NukeSetParameterValuesResultFailure)
        details = str(result.result_details)
        assert "could not read the workflow registry" in details
        assert not any(isinstance(r, SetParameterValueRequest) for r in engine.requests)
