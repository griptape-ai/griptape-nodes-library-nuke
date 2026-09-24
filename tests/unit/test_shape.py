from __future__ import annotations

import json
from typing import Any

import pytest

from nuke_host_api import shape
from nuke_host_api.protocol import VALUE_TYPES, ValueType
from tests.unit.host_api_fakes import SHAPE


class TestWorkflowShape:
    def test_a_dict_passes_through(self) -> None:
        assert shape.workflow_shape({"workflow_shape": SHAPE}) == SHAPE

    def test_a_json_string_is_parsed(self) -> None:
        assert shape.workflow_shape({"workflow_shape": json.dumps(SHAPE)}) == SHAPE

    @pytest.mark.parametrize("raw", [None, "", "   ", "not json at all", "[]", "123"])
    def test_anything_else_is_an_empty_shape(self, raw: Any) -> None:
        assert shape.workflow_shape({"workflow_shape": raw}) == {}

    def test_a_missing_field_is_an_empty_shape(self) -> None:
        assert shape.workflow_shape({}) == {}


class TestDeclaredParameters:
    def test_control_parameters_are_dropped(self) -> None:
        names = {declared["parameter"] for declared in shape.declared_parameters(SHAPE["inputs"])}
        assert "exec_out" not in names
        assert names == {"topic", "plate"}

    def test_node_and_parameter_are_split_out(self) -> None:
        declared = next(p for p in shape.declared_parameters(SHAPE["inputs"]) if p["parameter"] == "topic")
        assert declared["node"] == "Start Flow"
        assert declared["parameter"] == "topic"

    def test_a_label_is_the_parameters_own_name_not_the_node_and_the_parameter(self) -> None:
        labels = {declared["parameter"]: declared["name"] for declared in shape.declared_parameters(SHAPE["inputs"])}
        assert labels == {"topic": "Topic", "plate": "plate"}

    def test_a_dropdown_publishes_its_choices(self) -> None:
        section = {
            "Start Flow": {
                "size": {
                    "type": "str",
                    "ui_options": {"simple_dropdown": ["1024x1024", "1536x1024"], "show_search": True},
                }
            }
        }

        declared = shape.declared_parameters(section)[0]

        assert declared["choices"] == ["1024x1024", "1536x1024"]

    def test_an_engine_flag_beside_the_choices_is_not_published(self) -> None:
        """The engine's allow_custom stays engine-side: nothing here promises the set is enforced."""
        section = {
            "Start Flow": {"model": {"type": "str", "ui_options": {"simple_dropdown": ["flux"], "allow_custom": True}}}
        }

        declared = shape.declared_parameters(section)[0]

        assert declared["choices"] == ["flux"]
        assert "allow_custom" not in declared

    def test_choices_are_a_copy_of_what_the_engine_holds(self) -> None:
        """The Options trait hands out its live list, which a host must not be able to mutate."""
        engine_choices = ["flux", "sdxl"]
        section = {"Start Flow": {"model": {"type": "str", "ui_options": {"simple_dropdown": engine_choices}}}}

        declared = shape.declared_parameters(section)[0]
        declared["choices"].append("invented")

        assert engine_choices == ["flux", "sdxl"]

    def test_a_parameter_with_no_dropdown_has_no_choices(self) -> None:
        """An empty list, never a missing key."""
        declared = shape.declared_parameters(SHAPE["inputs"])
        assert all(entry["choices"] == [] for entry in declared)

    def test_a_parameter_the_author_hid_is_reported_hidden(self) -> None:
        section = {
            "Start Flow": {
                "counter": {"type": "int", "ui_options": {"hide": True}},
                "topic": {"type": "str"},
            }
        }

        hidden = {declared["parameter"]: declared["hidden"] for declared in shape.declared_parameters(section)}

        assert hidden == {"counter": True, "topic": False}

    def test_a_parameter_hidden_only_in_the_editors_property_panel_is_not_hidden(self) -> None:
        section = {"Start Flow": {"plate": {"type": "ImageUrlArtifact", "ui_options": {"hide_property": True}}}}

        assert shape.declared_parameters(section)[0]["hidden"] is False

    @pytest.mark.parametrize(
        ("parameter", "expected"),
        [
            ({"type": "str", "default_value": "a quiet harbour"}, "a quiet harbour"),
            ({"type": "int", "default_value": 24}, 24),
            ({"type": "float", "default_value": 23.976}, 23.976),
            ({"type": "bool", "default_value": True}, True),
            ({"type": "ImageUrlArtifact", "default_value": None}, None),
            ({"type": "ImageUrlArtifact", "default_value": ""}, None),
            (
                {"type": "ImageUrlArtifact", "default_value": "/show/plate.exr"},
                {"path": "/show/plate.exr", "format": "exr"},
            ),
            ({"type": "list[int]", "default_value": [42]}, [42]),
            ({"type": "list[int]", "default_value": None}, []),
            ({"type": "str"}, None),
        ],
    )
    def test_a_default_has_the_same_shape_as_a_value(self, parameter: dict, expected: Any) -> None:
        declared = shape.declared_parameters({"Start Flow": {"p": parameter}})[0]
        assert declared["default_value"] == expected

    def test_a_windows_default_path_is_slash_normalized(self) -> None:
        """Nuke's TCL layer reads a backslash as an escape."""
        section = {"Start Flow": {"plate": {"type": "ImageUrlArtifact", "default_value": "C:\\show\\plate.exr"}}}
        assert shape.declared_parameters(section)[0]["default_value"]["path"] == "C:/show/plate.exr"

    def test_a_sequence_default_keeps_one_entry_per_frame(self) -> None:
        section = {
            "Start Flow": {
                "plate": {
                    "type": "Sequence",
                    "default_value": ["/show/plate.0001.exr", "/show/plate.0002.exr"],
                }
            }
        }
        assert [entry["path"] for entry in shape.declared_parameters(section)[0]["default_value"]] == [
            "/show/plate.0001.exr",
            "/show/plate.0002.exr",
        ]

    @pytest.mark.parametrize(("engine_type", "expected"), [("ImageUrlArtifact", None), ("list[ImageUrlArtifact]", [])])
    def test_a_default_with_no_host_form_is_empty(self, engine_type: str, expected: Any) -> None:
        section = {"Start Flow": {"plate": {"type": engine_type, "default_value": "https://cdn.example.com/a.png"}}}
        assert shape.declared_parameters(section)[0]["default_value"] == expected

    @pytest.mark.parametrize(
        ("engine_type", "expected"),
        [("list[ImageUrlArtifact]", True), ("Sequence", True), ("ImageUrlArtifact", False), ("any", None)],
    )
    def test_list_cardinality_is_declared(self, engine_type: str, expected: bool | None) -> None:
        section = {"Start Flow": {"p": {"type": engine_type}}}
        assert shape.declared_parameters(section)[0]["is_list"] is expected

    def test_types_are_narrowed_to_the_closed_set(self) -> None:
        types = {declared["parameter"]: declared["type"] for declared in shape.declared_parameters(SHAPE["inputs"])}
        assert types == {"topic": ValueType.TEXT, "plate": ValueType.IMAGE}

    def test_an_out_of_scope_engine_type_degrades(self) -> None:
        """AudioUrlArtifact is outside the v1 set, so it must not leak through."""
        types = {declared["parameter"]: declared["type"] for declared in shape.declared_parameters(SHAPE["outputs"])}
        assert types["mixed_audio"] == ValueType.FILE
        assert all(declared["type"] in VALUE_TYPES for declared in shape.declared_parameters(SHAPE["outputs"]))

    @pytest.mark.parametrize("section", [None, {}, "string", 7, {"Node": "not a dict"}, {"Node": {"p": "not a dict"}}])
    def test_malformed_sections_yield_no_parameters_rather_than_raising(self, section: Any) -> None:
        assert shape.declared_parameters(section) == []


class TestInputParameterIds:
    def test_only_input_side_data_parameters_are_listed(self) -> None:
        assert shape.input_parameter_ids({"workflow_shape": SHAPE}) == {
            ("Start Flow", "topic"),
            ("Start Flow", "plate"),
        }

    def test_a_workflow_with_no_shape_allows_nothing(self) -> None:
        assert shape.input_parameter_ids({}) == set()

    def test_identity_is_read_without_normalizing_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Normalizing a macro-templated default issues an engine request this caller discards."""

        def explode(*_args: Any, **_kwargs: Any) -> Any:
            msg = "input_parameter_ids must not normalize defaults; it needs identity only"
            raise AssertionError(msg)

        monkeypatch.setattr(shape, "normalize_value", explode)

        assert shape.input_parameter_ids({"workflow_shape": SHAPE})


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
