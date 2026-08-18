"""Tests for the translation handlers.

Focused on the parts that decide what a host sees: how the engine's workflow shape is
parsed, how ports are narrowed, and how negotiation refuses an unsupported host.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from nuke_host_api import handlers
from nuke_host_api.events import (
    NukeConnectRequest,
    NukeConnectResultFailure,
    NukeConnectResultSuccess,
)
from nuke_host_api.protocol import PROTOCOL_VERSION, VALUE_TYPES, ValueType

SHAPE = {
    "inputs": {
        "Start Flow": {
            "exec_out": {"type": "parametercontroltype"},
            "topic": {"type": "str"},
            "plate": {"type": "ImageUrlArtifact"},
        }
    },
    "outputs": {
        "End Flow": {
            "exec_in": {"type": "parametercontroltype"},
            "was_successful": {"type": "bool"},
            "mixed_audio": {"type": "AudioUrlArtifact"},
        }
    },
}


class TestWorkflowShape:
    """The engine sends this field as a dict, a JSON string, or not at all."""

    def test_a_dict_passes_through(self) -> None:
        assert handlers._workflow_shape({"workflow_shape": SHAPE}) == SHAPE

    def test_a_json_string_is_parsed(self) -> None:
        """The case that silently produced zero ports for every workflow."""
        assert handlers._workflow_shape({"workflow_shape": json.dumps(SHAPE)}) == SHAPE

    @pytest.mark.parametrize("raw", [None, "", "   ", "not json at all", "[]", "123"])
    def test_anything_else_is_an_empty_shape(self, raw: Any) -> None:
        assert handlers._workflow_shape({"workflow_shape": raw}) == {}

    def test_a_missing_field_is_an_empty_shape(self) -> None:
        assert handlers._workflow_shape({}) == {}


class TestPorts:
    """Ports are the only workflow detail a host sees."""

    def test_control_parameters_are_dropped(self) -> None:
        """exec_in and exec_out are execution wiring, not data."""
        names = {port["parameter"] for port in handlers._ports(SHAPE["inputs"])}
        assert "exec_out" not in names
        assert names == {"topic", "plate"}

    def test_node_and_parameter_are_split_out(self) -> None:
        """run_workflow addresses inputs by the pair, so it cannot be a joined string."""
        port = next(p for p in handlers._ports(SHAPE["inputs"]) if p["parameter"] == "topic")
        assert port["node"] == "Start Flow"
        assert port["parameter"] == "topic"
        assert port["name"] == "Start Flow.topic"

    def test_types_are_narrowed_to_the_closed_set(self) -> None:
        types = {port["parameter"]: port["type"] for port in handlers._ports(SHAPE["inputs"])}
        assert types == {"topic": ValueType.TEXT, "plate": ValueType.IMAGE}

    def test_an_out_of_scope_engine_type_degrades(self) -> None:
        """AudioUrlArtifact is outside the v1 set, so it must not leak through."""
        types = {port["parameter"]: port["type"] for port in handlers._ports(SHAPE["outputs"])}
        assert types["mixed_audio"] == ValueType.FILE
        assert all(port["type"] in VALUE_TYPES for port in handlers._ports(SHAPE["outputs"]))

    @pytest.mark.parametrize("section", [None, {}, "string", 7, {"Node": "not a dict"}, {"Node": {"p": "not a dict"}}])
    def test_malformed_sections_yield_no_ports_rather_than_raising(self, section: Any) -> None:
        assert handlers._ports(section) == []


class FakeEngine:
    """Minimal facade stand-in for handlers that only need version and session lookups."""

    @staticmethod
    def handle_request(request: Any) -> Any:  # noqa: ARG004
        from griptape_nodes.retained_mode.events.app_events import GetEngineVersionResultSuccess

        return GetEngineVersionResultSuccess(major=0, minor=97, patch=0, result_details="ok")

    @staticmethod
    def get_session_id() -> str:
        return "session-abc"

    @staticmethod
    def get_engine_id() -> str:
        return "engine-xyz"


class TestConnect:
    @pytest.fixture(autouse=True)
    def _fake_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(handlers, "GriptapeNodes", FakeEngine)

    def test_a_matching_version_connects(self) -> None:
        result = handlers.handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION]))
        assert isinstance(result, NukeConnectResultSuccess)
        assert result.protocol_version == PROTOCOL_VERSION
        assert result.value_types == list(VALUE_TYPES)

    def test_the_event_topic_is_handed_over(self) -> None:
        """A host cannot derive this, so failing to return it strands notifications."""
        result = handlers.handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION]))
        assert isinstance(result, NukeConnectResultSuccess)
        assert result.event_topic == "sessions/session-abc/response"

    def test_an_empty_offer_assumes_the_current_version(self) -> None:
        """Keeps a bare connectivity check working."""
        result = handlers.handle_connect(NukeConnectRequest())
        assert isinstance(result, NukeConnectResultSuccess)

    def test_an_unsupported_version_is_refused_with_the_window(self) -> None:
        result = handlers.handle_connect(NukeConnectRequest(client_protocol_versions=[99]))
        assert isinstance(result, NukeConnectResultFailure)
        assert result.supported_protocol_versions
        assert "99" in str(result.result_details)

    def test_the_highest_mutual_version_wins(self) -> None:
        result = handlers.handle_connect(NukeConnectRequest(client_protocol_versions=[99, PROTOCOL_VERSION]))
        assert isinstance(result, NukeConnectResultSuccess)
        assert result.protocol_version == PROTOCOL_VERSION

    def test_a_wrong_request_type_raises(self) -> None:
        """Guards against a registry mix-up routing the wrong payload here."""
        with pytest.raises(TypeError):
            handlers.handle_connect(NukeConnectRequest)  # type: ignore[arg-type]
