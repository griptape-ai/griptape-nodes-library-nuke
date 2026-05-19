from __future__ import annotations

from script_parser.knob_type_map import griptape_type_for_knob, resolve_exposed_knob_type


class TestGriptapeTypeForKnob:
    def test_double_knob_maps_to_float(self) -> None:
        assert griptape_type_for_knob("Double_Knob") == "float"

    def test_int_knob_maps_to_int(self) -> None:
        assert griptape_type_for_knob("Int_Knob") == "int"

    def test_bool_knob_maps_to_bool(self) -> None:
        assert griptape_type_for_knob("Bool_Knob") == "bool"

    def test_boolean_knob_alias_maps_to_bool(self) -> None:
        assert griptape_type_for_knob("Boolean_Knob") == "bool"

    def test_string_knob_maps_to_str(self) -> None:
        assert griptape_type_for_knob("String_Knob") == "str"

    def test_enumeration_knob_maps_to_str(self) -> None:
        assert griptape_type_for_knob("Enumeration_Knob") == "str"

    def test_file_knob_maps_to_str(self) -> None:
        assert griptape_type_for_knob("File_Knob") == "str"

    def test_color_knob_maps_to_str(self) -> None:
        assert griptape_type_for_knob("Color_Knob") == "str"

    def test_acolor_knob_maps_to_float(self) -> None:
        assert griptape_type_for_knob("AColor_Knob") == "float"

    def test_xy_knob_maps_to_str(self) -> None:
        assert griptape_type_for_knob("XY_Knob") == "str"

    def test_array_knob_maps_to_float(self) -> None:
        assert griptape_type_for_knob("Array_Knob") == "float"

    def test_unknown_class_falls_back_to_str(self) -> None:
        assert griptape_type_for_knob("Mystery_Knob") == "str"

    def test_empty_string_falls_back_to_str(self) -> None:
        assert griptape_type_for_knob("") == "str"


class TestResolveExposedKnobType:
    _SCHEMA: dict[str, dict] = {
        "Grade1": {
            "class": "Grade",
            "knobs": {
                "gain": {"type": "Array_Knob", "value": 1.0},
                "black": {"type": "Double_Knob", "value": 0.0},
                "enable": {"type": "Boolean_Knob", "value": False},
                "label": {"type": "String_Knob", "value": ""},
            },
        },
    }

    def test_resolves_array_knob_to_float(self) -> None:
        assert resolve_exposed_knob_type("Grade1", "gain", self._SCHEMA) == "float"

    def test_resolves_double_knob_to_float(self) -> None:
        assert resolve_exposed_knob_type("Grade1", "black", self._SCHEMA) == "float"

    def test_resolves_boolean_knob_to_bool(self) -> None:
        assert resolve_exposed_knob_type("Grade1", "enable", self._SCHEMA) == "bool"

    def test_resolves_string_knob_to_str(self) -> None:
        assert resolve_exposed_knob_type("Grade1", "label", self._SCHEMA) == "str"

    def test_none_schema_returns_str(self) -> None:
        assert resolve_exposed_knob_type("Grade1", "gain", None) == "str"

    def test_missing_node_returns_str(self) -> None:
        assert resolve_exposed_knob_type("NoSuchNode", "gain", self._SCHEMA) == "str"

    def test_missing_knob_returns_str(self) -> None:
        assert resolve_exposed_knob_type("Grade1", "no_such_knob", self._SCHEMA) == "str"
