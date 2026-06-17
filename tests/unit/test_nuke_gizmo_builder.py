from __future__ import annotations

import pytest

from publish_gizmo.nuke_gizmo_builder import NukeGizmoBuilder


def _minimal_shape(input_params: dict[str, dict]) -> dict:
    return {
        "input": {"Nuke Start Flow": input_params},
        "output": {"Nuke End Flow": {}},
    }


def _generate_gizmo(input_params: dict[str, dict]) -> str:
    builder = NukeGizmoBuilder(
        workflow_name="test_workflow",
        workflow_shape=_minimal_shape(input_params),
        companion_dir="/tmp/test",
        workflow_file="/tmp/test/test_workflow.json",
        current_version=1,
    )
    return builder.generate()


class TestEmptyStringDefaultIgnoredForNumericTypes:
    """Dynamically added params have default_value="" which must not emit a default line."""

    def test_int_param_with_empty_string_default_omits_default(self) -> None:
        gizmo = _generate_gizmo({"count": {"type": "int", "default_value": ""}})
        lines = gizmo.splitlines()
        assert any("{3 count" in line for line in lines)
        value_lines = [line for line in lines if line.strip().startswith("count ")]
        assert value_lines == []

    def test_float_param_with_empty_string_default_omits_default(self) -> None:
        gizmo = _generate_gizmo({"scale": {"type": "float", "default_value": ""}})
        lines = gizmo.splitlines()
        assert any("{7 scale" in line for line in lines)
        value_lines = [line for line in lines if line.strip().startswith("scale ")]
        assert value_lines == []

    def test_bool_param_with_empty_string_default_omits_default(self) -> None:
        gizmo = _generate_gizmo({"enabled": {"type": "bool", "default_value": ""}})
        lines = gizmo.splitlines()
        assert any("{6 enabled" in line for line in lines)
        value_lines = [line for line in lines if line.strip().startswith("enabled ")]
        assert value_lines == []


class TestValidDefaultsArePreserved:
    """Correct-typed defaults must still appear in the output."""

    def test_int_param_with_valid_default(self) -> None:
        gizmo = _generate_gizmo({"count": {"type": "int", "default_value": 5}})
        lines = gizmo.splitlines()
        assert any(line.strip() == "count 5" for line in lines)

    def test_float_param_with_valid_default(self) -> None:
        gizmo = _generate_gizmo({"scale": {"type": "float", "default_value": 2.5}})
        lines = gizmo.splitlines()
        assert any(line.strip() == "scale 2.5" for line in lines)

    def test_bool_param_with_true_default(self) -> None:
        gizmo = _generate_gizmo({"enabled": {"type": "bool", "default_value": True}})
        lines = gizmo.splitlines()
        assert any(line.strip() == "enabled 1" for line in lines)

    def test_bool_param_with_false_default(self) -> None:
        gizmo = _generate_gizmo({"enabled": {"type": "bool", "default_value": False}})
        lines = gizmo.splitlines()
        assert any(line.strip() == "enabled 0" for line in lines)

    def test_string_param_with_valid_default(self) -> None:
        gizmo = _generate_gizmo({"prompt": {"type": "str", "default_value": "hello"}})
        lines = gizmo.splitlines()
        assert any('prompt "hello"' in line for line in lines)


class TestNoneDefaultOmitsValueLine:
    """None default_value must not emit a value line for any type."""

    @pytest.mark.parametrize("param_type", ["int", "float", "bool", "str"])
    def test_none_default_omits_value_line(self, param_type: str) -> None:
        gizmo = _generate_gizmo({"param": {"type": param_type, "default_value": None}})
        lines = gizmo.splitlines()
        value_lines = [line for line in lines if line.strip().startswith("param ") and "addUserKnob" not in line]
        assert value_lines == []


class TestMismatchedDefaultTypeIgnored:
    """A default of the wrong type for a numeric knob must be silently dropped."""

    def test_string_default_for_int_param_ignored(self) -> None:
        gizmo = _generate_gizmo({"count": {"type": "int", "default_value": "three"}})
        lines = gizmo.splitlines()
        value_lines = [line for line in lines if line.strip().startswith("count ")]
        assert value_lines == []

    def test_string_default_for_float_param_ignored(self) -> None:
        gizmo = _generate_gizmo({"scale": {"type": "float", "default_value": "big"}})
        lines = gizmo.splitlines()
        value_lines = [line for line in lines if line.strip().startswith("scale ")]
        assert value_lines == []

    def test_string_default_for_bool_param_ignored(self) -> None:
        gizmo = _generate_gizmo({"flag": {"type": "bool", "default_value": "yes"}})
        lines = gizmo.splitlines()
        value_lines = [line for line in lines if line.strip().startswith("flag ")]
        assert value_lines == []


class TestSubclassDefaultsRejectedByStrictTypeCheck:
    """type(x) is T rejects subclass matches that isinstance would accept."""

    def test_bool_default_rejected_for_int_param(self) -> None:
        gizmo = _generate_gizmo({"count": {"type": "int", "default_value": True}})
        lines = gizmo.splitlines()
        value_lines = [line for line in lines if line.strip().startswith("count ")]
        assert value_lines == []

    def test_bool_default_rejected_for_float_param(self) -> None:
        gizmo = _generate_gizmo({"scale": {"type": "float", "default_value": False}})
        lines = gizmo.splitlines()
        value_lines = [line for line in lines if line.strip().startswith("scale ")]
        assert value_lines == []

    def test_int_default_rejected_for_float_param(self) -> None:
        gizmo = _generate_gizmo({"scale": {"type": "float", "default_value": 3}})
        lines = gizmo.splitlines()
        value_lines = [line for line in lines if line.strip().startswith("scale ")]
        assert value_lines == []
