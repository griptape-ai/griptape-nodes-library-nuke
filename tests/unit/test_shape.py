"""Tests for the shape projection.

The parts that decide what a host sees: how the engine's workflow_shape is parsed, how
ports are narrowed, and which workflows are worth offering. No engine involved, because
none of it issues a request.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from nuke_host_api import shape
from nuke_host_api.protocol import VALUE_TYPES, ValueType
from tests.unit.host_api_fakes import SHAPE


class TestWorkflowShape:
    """The engine sends this field as a dict, a JSON string, or not at all."""

    def test_a_dict_passes_through(self) -> None:
        assert shape.workflow_shape({"workflow_shape": SHAPE}) == SHAPE

    def test_a_json_string_is_parsed(self) -> None:
        """The case that silently produced zero ports for every workflow."""
        assert shape.workflow_shape({"workflow_shape": json.dumps(SHAPE)}) == SHAPE

    @pytest.mark.parametrize("raw", [None, "", "   ", "not json at all", "[]", "123"])
    def test_anything_else_is_an_empty_shape(self, raw: Any) -> None:
        assert shape.workflow_shape({"workflow_shape": raw}) == {}

    def test_a_missing_field_is_an_empty_shape(self) -> None:
        assert shape.workflow_shape({}) == {}


class TestPorts:
    """Ports are the only workflow detail a host sees."""

    def test_control_parameters_are_dropped(self) -> None:
        """exec_in and exec_out are execution wiring, not data."""
        names = {port["parameter"] for port in shape.ports(SHAPE["inputs"])}
        assert "exec_out" not in names
        assert names == {"topic", "plate"}

    def test_node_and_parameter_are_split_out(self) -> None:
        """run_workflow addresses inputs by the pair, so it cannot be a joined string."""
        port = next(p for p in shape.ports(SHAPE["inputs"]) if p["parameter"] == "topic")
        assert port["node"] == "Start Flow"
        assert port["parameter"] == "topic"
        assert port["name"] == "Start Flow.topic"

    def test_types_are_narrowed_to_the_closed_set(self) -> None:
        types = {port["parameter"]: port["type"] for port in shape.ports(SHAPE["inputs"])}
        assert types == {"topic": ValueType.TEXT, "plate": ValueType.IMAGE}

    def test_an_out_of_scope_engine_type_degrades(self) -> None:
        """AudioUrlArtifact is outside the v1 set, so it must not leak through."""
        types = {port["parameter"]: port["type"] for port in shape.ports(SHAPE["outputs"])}
        assert types["mixed_audio"] == ValueType.FILE
        assert all(port["type"] in VALUE_TYPES for port in shape.ports(SHAPE["outputs"]))

    @pytest.mark.parametrize("section", [None, {}, "string", 7, {"Node": "not a dict"}, {"Node": {"p": "not a dict"}}])
    def test_malformed_sections_yield_no_ports_rather_than_raising(self, section: Any) -> None:
        assert shape.ports(section) == []


class TestInputPortIds:
    """The allow-list execute checks a host's inputs against."""

    def test_only_input_side_data_ports_are_listed(self) -> None:
        assert shape.input_port_ids({"workflow_shape": SHAPE}) == {("Start Flow", "topic"), ("Start Flow", "plate")}

    def test_a_workflow_with_no_shape_allows_nothing(self) -> None:
        assert shape.input_port_ids({}) == set()

    def test_identity_is_read_without_normalizing_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Normalizing a macro-templated default issues an engine request this caller discards."""

        def explode(*_args: Any, **_kwargs: Any) -> Any:
            msg = "input_port_ids must not normalize defaults; it needs identity only"
            raise AssertionError(msg)

        monkeypatch.setattr(shape, "normalize_value", explode)

        assert shape.input_port_ids({"workflow_shape": SHAPE})


class TestIsRunnable:
    def test_a_workflow_with_no_shape_is_not_runnable(self) -> None:
        runnable, reason = shape.is_runnable({"workflow_shape": None})
        assert runnable is False
        assert "shape" in reason

    def test_a_workflow_with_no_file_path_is_not_runnable(self) -> None:
        runnable, reason = shape.is_runnable({"workflow_shape": SHAPE, "file_path": None})
        assert runnable is False
        assert "file path" in reason

    def test_a_missing_file_on_disk_is_not_runnable(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        missing = tmp_path / "gone.py"
        monkeypatch.setattr(shape.WorkflowRegistry, "get_complete_file_path", staticmethod(lambda p: str(p)))

        runnable, reason = shape.is_runnable({"workflow_shape": SHAPE, "file_path": str(missing)})

        assert runnable is False
        assert "missing from disk" in reason

    def test_a_present_file_with_a_shape_is_runnable(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        present = tmp_path / "here.py"
        present.write_text("# workflow")
        monkeypatch.setattr(shape.WorkflowRegistry, "get_complete_file_path", staticmethod(lambda p: str(p)))

        runnable, reason = shape.is_runnable({"workflow_shape": SHAPE, "file_path": str(present)})

        assert runnable is True
        assert reason == ""
