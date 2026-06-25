from __future__ import annotations

import pytest

from publish_gizmo.nuke_gizmo_builder import NukeGizmoBuilder


def _minimal_shape(input_params: dict[str, dict]) -> dict:
    return {
        "input": {"Nuke Start Flow": input_params},
        "output": {"Nuke End Flow": {}},
    }


def _shape_with_output(output_params: dict[str, dict]) -> dict:
    return {
        "input": {"Nuke Start Flow": {}},
        "output": {"Nuke End Flow": output_params},
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


def _generate_gizmo_with_output(output_params: dict[str, dict]) -> str:
    builder = NukeGizmoBuilder(
        workflow_name="test_workflow",
        workflow_shape=_shape_with_output(output_params),
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


class TestReadNodeExpressionLink:
    """Internal Read nodes must expression-link their file knob to the
    persistent top-level output knob so the path survives .nk save/reload
    and copy-paste (Nuke does not serialize internal gizmo-node edits into
    the .nk).
    """

    def test_single_media_output_read_node_links_to_output_knob(self) -> None:
        """A single image output generates a Read whose file is linked to image_out."""
        gizmo = _generate_gizmo_with_output(
            {
                "image": {
                    "type": "ImageUrlArtifact",
                    "default_value": "",
                    "mode_allowed_output": True,
                    "ui_options": {},
                }
            }
        )
        # The internal Read node must carry the TCL expression, not an empty literal.
        assert r'file "\[value parent.image_out]"' in gizmo
        # Sanity: the top-level output knob must still be declared.
        assert "image_out" in gizmo

    def test_single_media_output_no_literal_file_empty(self) -> None:
        """The hardcoded 'file ""' must not appear when an expression is used."""
        gizmo = _generate_gizmo_with_output(
            {
                "result": {
                    "type": "ImageUrlArtifact",
                    "default_value": "",
                    "mode_allowed_output": True,
                    "ui_options": {},
                }
            }
        )
        # Expression-linked Read must not fall back to the empty literal.
        assert 'file ""' not in gizmo

    def test_multiple_media_outputs_each_read_links_to_its_own_knob(self) -> None:
        """Multiple image outputs each get a Read linked to their own *_out knob."""
        gizmo = _generate_gizmo_with_output(
            {
                "alpha": {
                    "type": "ImageUrlArtifact",
                    "default_value": "",
                    "mode_allowed_output": True,
                    "ui_options": {},
                },
                "beauty": {
                    "type": "ImageUrlArtifact",
                    "default_value": "",
                    "mode_allowed_output": True,
                    "ui_options": {},
                },
            }
        )
        assert r'file "\[value parent.alpha_out]"' in gizmo
        assert r'file "\[value parent.beauty_out]"' in gizmo
        # No empty literals anywhere.
        assert 'file ""' not in gizmo

    def test_non_media_output_does_not_produce_read_node(self) -> None:
        """A plain string output has no Read node and no expression."""
        gizmo = _generate_gizmo_with_output(
            {
                "caption": {
                    "type": "str",
                    "default_value": "",
                    "mode_allowed_output": True,
                    "ui_options": {},
                }
            }
        )
        assert "GEN_READ" not in gizmo
        assert r"\[value" not in gizmo
