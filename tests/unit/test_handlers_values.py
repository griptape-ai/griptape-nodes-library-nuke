"""Tests for the bulk port-value read verb."""

from __future__ import annotations

from typing import Any

import pytest
from griptape_nodes.retained_mode.events.context_events import (
    GetWorkflowContextRequest,
    GetWorkflowContextSuccess,
)
from griptape_nodes.retained_mode.events.parameter_events import (
    GetParameterValueRequest,
    GetParameterValueResultFailure,
    GetParameterValueResultSuccess,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    ListAllWorkflowsRequest,
    ListAllWorkflowsResultSuccess,
)

from nuke_host_api.events import (
    NukeGetPortValuesRequest,
    NukeGetPortValuesResultFailure,
    NukeGetPortValuesResultSuccess,
)
from nuke_host_api.handlers import handle_get_port_values
from nuke_host_api.protocol import PortSection, ValueType
from tests.unit.host_api_fakes import SHAPE, use_engine

NOTHING_LOADED = {GetWorkflowContextRequest: GetWorkflowContextSuccess(workflow_name="", result_details="ok")}

WORKFLOW_LOADED: dict[type, Any] = {
    GetWorkflowContextRequest: GetWorkflowContextSuccess(workflow_name="wf1", result_details="ok"),
    ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(
        workflows={"wf1": {"workflow_shape": SHAPE}}, result_details="ok"
    ),
}


def _respond_to_get_value(request: GetParameterValueRequest) -> Any:
    if request.parameter_name == "topic":
        return GetParameterValueResultSuccess(
            input_types=["str"], type="str", output_type="str", value="a quiet harbour at dusk", result_details="ok"
        )
    if request.parameter_name == "plate":
        return GetParameterValueResultSuccess(
            input_types=["ImageUrlArtifact"],
            type="ImageUrlArtifact",
            output_type="ImageUrlArtifact",
            value=None,
            result_details="ok",
        )
    if request.parameter_name == "was_successful":
        return GetParameterValueResultSuccess(
            input_types=["bool"], type="bool", output_type="bool", value=True, result_details="ok"
        )
    if request.parameter_name == "mixed_audio":
        return GetParameterValueResultSuccess(
            input_types=["AudioUrlArtifact"],
            type="AudioUrlArtifact",
            output_type="AudioUrlArtifact",
            value="http://x/audio.mp3",
            result_details="ok",
        )
    msg = f"no fake response configured for parameter '{request.parameter_name}'"
    raise AssertionError(msg)


class TestGetPortValues:
    def test_no_sections_requested_reads_both_sides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: _respond_to_get_value})

        result = handle_get_port_values(NukeGetPortValuesRequest())

        assert isinstance(result, NukeGetPortValuesResultSuccess)
        assert result.workflow_id == "wf1"
        assert set(result.requested_sections) == {PortSection.INPUTS, PortSection.OUTPUTS}
        assert result.inputs["Start Flow"]["topic"]["value_type"] == ValueType.TEXT
        assert result.outputs["End Flow"]["was_successful"]["value_type"] == ValueType.BOOL
        assert result.outputs["End Flow"]["mixed_audio"]["value_type"] == ValueType.FILE

    def test_a_single_section_reads_only_that_side(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: _respond_to_get_value})

        result = handle_get_port_values(NukeGetPortValuesRequest(sections=[PortSection.INPUTS]))

        assert isinstance(result, NukeGetPortValuesResultSuccess)
        assert result.requested_sections == [PortSection.INPUTS]
        assert result.inputs["Start Flow"]["topic"]["value_type"] == ValueType.TEXT
        assert result.outputs == {}
        read_parameters = {r.parameter_name for r in engine.requests if isinstance(r, GetParameterValueRequest)}
        assert read_parameters == {"topic", "plate"}, "must not read the output side when only inputs was requested"

    def test_an_unknown_section_is_refused_without_reaching_the_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: _respond_to_get_value})

        result = handle_get_port_values(NukeGetPortValuesRequest(sections=["sideways"]))

        assert isinstance(result, NukeGetPortValuesResultFailure)
        assert "sideways" in str(result.result_details)
        assert not any(isinstance(r, GetParameterValueRequest) for r in engine.requests)

    def test_fails_when_no_workflow_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, NOTHING_LOADED)

        result = handle_get_port_values(NukeGetPortValuesRequest())

        assert isinstance(result, NukeGetPortValuesResultFailure)
        assert not any(isinstance(r, GetParameterValueRequest) for r in engine.requests)

    def test_a_port_the_engine_will_not_answer_for_is_reported_not_omitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def respond(request: GetParameterValueRequest) -> Any:
            if request.parameter_name == "topic":
                return GetParameterValueResultFailure(result_details="node was deleted mid-read")
            return _respond_to_get_value(request)

        use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: respond})

        result = handle_get_port_values(NukeGetPortValuesRequest(sections=[PortSection.INPUTS]))

        assert isinstance(result, NukeGetPortValuesResultSuccess)
        assert "Start Flow" not in result.inputs or "topic" not in result.inputs.get("Start Flow", {})
        assert result.unavailable == [
            {
                "section": PortSection.INPUTS,
                "node": "Start Flow",
                "parameter": "topic",
                "reason": "node was deleted mid-read",
            }
        ]

    def test_control_parameters_are_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: _respond_to_get_value})

        result = handle_get_port_values(NukeGetPortValuesRequest())

        assert isinstance(result, NukeGetPortValuesResultSuccess)
        assert "exec_out" not in result.inputs.get("Start Flow", {})
        assert "exec_in" not in result.outputs.get("End Flow", {})

    def test_values_are_normalized_the_same_shape_as_a_describe_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {**WORKFLOW_LOADED, GetParameterValueRequest: _respond_to_get_value})

        result = handle_get_port_values(NukeGetPortValuesRequest())

        assert isinstance(result, NukeGetPortValuesResultSuccess)
        descriptor = result.outputs["End Flow"]["was_successful"]
        assert set(descriptor) == {"value_type", "sources", "colorspace", "engine_type"}
