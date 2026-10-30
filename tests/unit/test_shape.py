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
        ("engine_type", "expected"),
        [("list[ImageUrlArtifact]", True), ("Sequence", False), ("ImageUrlArtifact", False), ("any", None)],
    )
    def test_list_cardinality_is_declared(self, engine_type: str, expected: bool | None) -> None:
        section = {"Start Flow": {"p": {"type": engine_type}}}
        assert shape.declared_parameters(section)[0]["is_list"] is expected

    @pytest.mark.parametrize(
        ("engine_type", "expected"),
        [("Sequence", True), ("list[Sequence]", True), ("ImageUrlArtifact", False), ("str", False), ("any", False)],
    )
    def test_a_declared_sequence_is_marked(self, engine_type: str, expected: bool) -> None:
        section = {"Start Flow": {"p": {"type": engine_type}}}
        assert shape.declared_parameters(section)[0]["is_sequence"] is expected

    def test_a_sequence_is_still_an_image(self) -> None:
        section = {"Start Flow": {"frames": {"type": "Sequence"}}}
        assert shape.declared_parameters(section)[0]["type"] == ValueType.IMAGE

    def test_a_text_input_with_a_sequence_picker_is_not_a_sequence(self) -> None:
        picker = {"fileSystemPicker": {"allowSequences": True}}
        section = {"Start Flow": {"frames": {"type": "str", "ui_options": picker}}}
        assert shape.declared_parameters(section)[0]["is_sequence"] is False

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


class TestInputParameterTypes:
    def test_only_input_side_data_parameters_are_listed_with_their_engine_type(self) -> None:
        assert shape.input_parameter_types({"workflow_shape": SHAPE}) == {
            ("Start Flow", "topic"): "str",
            ("Start Flow", "plate"): "ImageUrlArtifact",
        }

    def test_a_workflow_with_no_shape_allows_nothing(self) -> None:
        assert shape.input_parameter_types({}) == {}


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
