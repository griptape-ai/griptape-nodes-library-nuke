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
)

from nuke_host_api import parameter_values
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
        engine = use_engine(monkeypatch, {GetParameterValueRequest: respond_to_get_value})

        parameter_values.read_sections(SHAPE, list(PARAMETER_SECTIONS))

        read = {r.parameter_name for r in engine.requests if isinstance(r, GetParameterValueRequest)}
        assert not read & {"exec_in", "exec_out"}
