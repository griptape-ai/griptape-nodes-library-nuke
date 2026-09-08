"""Tests for the shared parameter-value reader.

The reader is what stops ``NukeLoadWorkflowRequest`` and ``NukeGetParameterValuesRequest``
from disagreeing about what a parameter holds, so its behaviour is asserted here once rather
than twice through the two verbs that use it.
"""

from __future__ import annotations

from typing import Any

import pytest
from griptape_nodes.retained_mode.events.parameter_events import (
    GetParameterValueRequest,
    GetParameterValueResultFailure,
    SetParameterValueRequest,
    SetParameterValueResultFailure,
    SetParameterValueResultSuccess,
)

from nuke_host_api import engine, parameter_values
from nuke_host_api.protocol import PARAMETER_SECTIONS, ParameterSection, ValueType
from tests.unit.host_api_fakes import SHAPE, respond_to_get_value, use_engine


class TestReadSections:
    def test_both_sections_are_read_when_both_are_requested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {GetParameterValueRequest: respond_to_get_value})

        inputs, outputs, unavailable = parameter_values.read_sections(SHAPE, list(PARAMETER_SECTIONS))

        assert inputs["Start Flow"]["topic"]["value_type"] == ValueType.TEXT
        assert outputs["End Flow"]["was_successful"]["value_type"] == ValueType.BOOL
        assert unavailable == []

    def test_a_section_not_requested_comes_back_empty_and_unread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty map rather than a missing key, so no caller has to tell the two apart."""
        engine = use_engine(monkeypatch, {GetParameterValueRequest: respond_to_get_value})

        inputs, outputs, _ = parameter_values.read_sections(SHAPE, [ParameterSection.INPUTS])

        assert inputs
        assert outputs == {}
        read = {r.parameter_name for r in engine.requests if isinstance(r, GetParameterValueRequest)}
        assert read == {"topic", "plate"}

    def test_an_unreadable_parameter_is_tagged_with_the_section_it_came_from(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def respond(request: GetParameterValueRequest) -> Any:
            if request.parameter_name == "was_successful":
                return GetParameterValueResultFailure(result_details="node was deleted mid-read")
            return respond_to_get_value(request)

        use_engine(monkeypatch, {GetParameterValueRequest: respond})

        _, outputs, unavailable = parameter_values.read_sections(SHAPE, list(PARAMETER_SECTIONS))

        assert "was_successful" not in outputs.get("End Flow", {})
        assert unavailable == [
            {
                "section": ParameterSection.OUTPUTS,
                "node": "End Flow",
                "parameter": "was_successful",
                "reason": "node was deleted mid-read",
            }
        ]

    def test_a_value_the_engine_holds_as_none_is_a_value_not_a_miss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unset knob and one that could not be read mean different things to a host."""
        use_engine(monkeypatch, {GetParameterValueRequest: respond_to_get_value})

        inputs, _, unavailable = parameter_values.read_sections(SHAPE, [ParameterSection.INPUTS])

        assert inputs["Start Flow"]["plate"]["value_type"] == ValueType.NULL
        assert unavailable == []

    def test_an_empty_shape_reads_nothing_and_reports_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, {})

        inputs, outputs, unavailable = parameter_values.read_sections({}, list(PARAMETER_SECTIONS))

        assert (inputs, outputs, unavailable) == ({}, {}, [])
        assert engine.requests == []

    def test_control_parameters_are_never_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Execution wiring is not data, and the normalizer has no case for its type."""
        engine_fake = use_engine(monkeypatch, {GetParameterValueRequest: respond_to_get_value})

        parameter_values.read_sections(SHAPE, list(PARAMETER_SECTIONS))

        read = {r.parameter_name for r in engine_fake.requests if isinstance(r, GetParameterValueRequest)}
        assert not read & {"exec_in", "exec_out"}


class TestApplyInputs:
    """Shared by NukeExecuteWorkflowRequest and NukeSetParameterValuesRequest.

    Asserted here once, against the module both verbs call into, rather than through either
    handler, so the two cannot silently diverge on what "applied" and "rejected" mean.
    """

    def test_applied_and_rejected_inputs_are_tracked_separately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def respond(request: SetParameterValueRequest) -> Any:
            if request.parameter_name == "good":
                return SetParameterValueResultSuccess(finalized_value=1, data_type="int", result_details="ok")
            return SetParameterValueResultFailure(result_details="rejected: wrong type")

        use_engine(monkeypatch, {SetParameterValueRequest: respond})

        applied, rejected = parameter_values.apply_inputs(
            {"Node A": {"good": 1, "bad": "nope"}}, {("Node A", "good"), ("Node A", "bad")}
        )

        assert applied == [{"node": "Node A", "parameter": "good"}]
        assert rejected == [{"node": "Node A", "parameter": "bad", "reason": "rejected: wrong type"}]

    def test_a_non_dict_parameters_value_is_rejected_without_calling_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine_fake = use_engine(monkeypatch, {})

        applied, rejected = parameter_values.apply_inputs({"Node A": "not a dict"}, {("Node A", "good")})  # type: ignore[arg-type]

        assert applied == []
        assert rejected == [{"node": "Node A", "parameter": "*", "reason": "Expected an object of parameters."}]
        assert engine_fake.requests == []

    def test_a_pair_outside_the_allow_list_is_rejected_without_calling_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine_fake = use_engine(monkeypatch, {})

        applied, rejected = parameter_values.apply_inputs({"Node A": {"secret": 1}}, set())

        assert applied == []
        assert rejected == [
            {"node": "Node A", "parameter": "secret", "reason": "Not a declared input parameter of this workflow."}
        ]
        assert engine_fake.requests == []


class TestUnaddressableInputsReason:
    """Shared by NukeExecuteWorkflowRequest and NukeSetParameterValuesRequest.

    Each caller supplies its own ``no_inputs_remedy``, the one sentence that differs between
    a verb that still has a graph to run as-is and one that has nothing left to do at all.
    """

    def test_nothing_is_wrong_when_the_workflow_declares_the_requested_inputs(self) -> None:
        found = engine.WorkflowLookup(entry={"name": "wf1"}, registry_readable=True)

        reason = parameter_values.unaddressable_inputs_reason(
            "wf1", found, {("Start Flow", "topic")}, no_inputs_remedy="do nothing"
        )

        assert reason is None

    def test_an_unreadable_registry_names_a_retry_and_the_callers_own_remedy(self) -> None:
        found = engine.WorkflowLookup(entry=None, registry_readable=False)

        reason = parameter_values.unaddressable_inputs_reason(
            "wf1", found, set(), no_inputs_remedy="send no values, since there is nothing else to do"
        )

        assert reason is not None
        because, error = reason
        assert "could not read the workflow registry" in because
        assert "send no values, since there is nothing else to do" in because
        assert error is RuntimeError

    def test_a_loaded_id_missing_from_a_readable_registry_names_a_reload_not_the_callers_remedy(self) -> None:
        found = engine.WorkflowLookup(entry=None, registry_readable=True)

        reason = parameter_values.unaddressable_inputs_reason(
            "wf1", found, set(), no_inputs_remedy="send no values, since there is nothing else to do"
        )

        assert reason is not None
        because, error = reason
        assert "no longer in the registry" in because
        assert "NukeLoadWorkflowRequest" in because
        assert "send no values" not in because
        assert error is KeyError

    def test_a_graph_with_no_declared_inputs_names_the_callers_own_remedy(self) -> None:
        found = engine.WorkflowLookup(entry={"name": "Untitled"}, registry_readable=True)

        reason = parameter_values.unaddressable_inputs_reason(
            "unsaved:9f0c", found, set(), no_inputs_remedy="do nothing"
        )

        assert reason is not None
        because, error = reason
        assert "declares no input parameters" in because
        assert "do nothing" in because
        assert error is RuntimeError
