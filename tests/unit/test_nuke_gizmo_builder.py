from __future__ import annotations

import ast

import pytest

from publish_gizmo.constants import OUTPUTS_DIR_NAME
from publish_gizmo.nuke_gizmo_builder import NukeGizmoBuilder, _build_knob_changed_code


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


class TestCrossTypedDefaultsAreCoerced:
    """A value carried over from the canvas may not match the param's declared type.

    Emitting nothing leaves Nuke to initialize the knob to 0, which run_button then
    sends back as a real input.
    """

    def test_int_param_with_string_default_emits_value(self) -> None:
        gizmo = _generate_gizmo({"seed": {"type": "int", "default_value": "42"}})
        assert any(line.strip() == "seed 42" for line in gizmo.splitlines())

    def test_float_param_with_int_default_emits_value(self) -> None:
        gizmo = _generate_gizmo({"scale": {"type": "float", "default_value": 5}})
        assert any(line.strip() == "scale 5.0" for line in gizmo.splitlines())

    def test_int_param_with_float_default_truncates(self) -> None:
        gizmo = _generate_gizmo({"count": {"type": "int", "default_value": 2.7}})
        assert any(line.strip() == "count 2" for line in gizmo.splitlines())

    def test_bool_param_with_string_default_emits_value(self) -> None:
        gizmo = _generate_gizmo({"enabled": {"type": "bool", "default_value": "true"}})
        assert any(line.strip() == "enabled 1" for line in gizmo.splitlines())

    def test_int_param_with_bool_default_omits_value(self) -> None:
        # A checkbox value on an int knob is a type mismatch, not a 0/1 the user chose.
        gizmo = _generate_gizmo({"count": {"type": "int", "default_value": True}})
        assert [line for line in gizmo.splitlines() if line.strip().startswith("count ")] == []

    def test_int_param_with_unparseable_default_omits_value(self) -> None:
        gizmo = _generate_gizmo({"count": {"type": "int", "default_value": "abc"}})
        assert [line for line in gizmo.splitlines() if line.strip().startswith("count ")] == []

    def test_zero_is_emitted_not_treated_as_absent(self) -> None:
        gizmo = _generate_gizmo({"seed": {"type": "int", "default_value": 0}})
        assert any(line.strip() == "seed 0" for line in gizmo.splitlines())

    def test_string_param_with_int_default_emits_text(self) -> None:
        gizmo = _generate_gizmo({"label": {"type": "str", "default_value": 7}})
        assert any('label "7"' in line for line in gizmo.splitlines())

    def test_string_param_with_object_default_omits_value(self) -> None:
        # An artifact would stringify to a Python repr, and the writer's TCL escaping
        # needs a str at all.
        gizmo = _generate_gizmo({"image": {"type": "str", "default_value": {"a": 1}}})
        assert [line for line in gizmo.splitlines() if line.strip().startswith('image "')] == []

    def test_dropdown_uses_selected_value_index(self) -> None:
        gizmo = _generate_gizmo(
            {
                "mode": {
                    "type": "str",
                    "default_value": "fast",
                    "ui_options": {"simple_dropdown": ["slow", "fast"]},
                }
            }
        )
        assert any(line.strip() == "mode 1" for line in gizmo.splitlines())


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

    def test_unrecognized_string_default_for_bool_param_ignored(self) -> None:
        gizmo = _generate_gizmo({"flag": {"type": "bool", "default_value": "maybe"}})
        lines = gizmo.splitlines()
        value_lines = [line for line in lines if line.strip().startswith("flag ")]
        assert value_lines == []


class TestBoolDefaultsRejectedForNumericParams:
    """A checkbox value on a numeric knob is a type mismatch, not a 0/1 the user chose."""

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
        assert r'file "\[value' not in gizmo


class TestTclExpressionDefaultsEscaped:
    """Defaults containing TCL brackets must be escaped so they survive gizmo parse as literal text."""

    def test_str_default_with_expression_is_escaped(self) -> None:
        gizmo = _generate_gizmo({"prompt": {"type": "str", "default_value": "[value this.name]"}})
        assert r' prompt "\[value this.name]"' in gizmo
        assert ' prompt "[value this.name]"' not in gizmo

    def test_str_default_with_quote_is_escaped(self) -> None:
        gizmo = _generate_gizmo({"prompt": {"type": "str", "default_value": 'say "hi"'}})
        assert r' prompt "say \"hi\""' in gizmo

    def test_file_default_with_expression_is_escaped(self) -> None:
        gizmo = _generate_gizmo({"image": {"type": "ImageUrlArtifact", "default_value": "[frame].jpg"}})
        assert r' image "\[frame].jpg"' in gizmo

    def test_plain_default_unchanged(self) -> None:
        gizmo = _generate_gizmo({"prompt": {"type": "str", "default_value": "hello world"}})
        assert ' prompt "hello world"' in gizmo


class TestTclHintTooltips:
    """String-family input knobs and output knobs must carry TCL-expression tooltips."""

    def test_str_input_knob_has_expression_tooltip(self) -> None:
        gizmo = _generate_gizmo({"folder_path": {"type": "str", "default_value": ""}})
        knob_line = next(line for line in gizmo.splitlines() if "addUserKnob {1 folder_path" in line)
        assert ' t "' in knob_line
        assert r"\[value this.name]" in knob_line

    def test_tooltips_never_contain_unescaped_brackets(self) -> None:
        gizmo = _generate_gizmo({"folder_path": {"type": "str", "default_value": ""}})
        for line in gizmo.splitlines():
            # Check the tooltip attribute (t "...") on EVERY knob, including {22}
            # PyScript buttons — their _COPY_LINK_TOOLTIP / _LINK_BUTTON_TOOLTIP
            # contain [value ...] and must be escaped. Only the tooltip substring
            # is checked so the T "..." script body (where brackets have no TCL
            # significance, since Nuke does not substitute inside a script attr)
            # does not produce false positives.
            if ' t "' not in line:
                continue
            tooltip = line.split(' t "', 1)[1].split('"', 1)[0]
            assert "[value" not in tooltip.replace(r"\[value", "")
            assert "[file" not in tooltip.replace(r"\[file", "")
            assert "[frame" not in tooltip.replace(r"\[frame", "")

    def test_copy_link_tooltip_escapes_brackets(self) -> None:
        """The Copy Link button's tooltip contains [value ...] and must be escaped."""
        gizmo = _generate_gizmo_with_output(
            {"caption": {"type": "str", "default_value": "", "mode_allowed_output": True, "ui_options": {}}}
        )
        button_line = next(line for line in gizmo.splitlines() if "addUserKnob {22 _copy_caption_out" in line)
        assert ' t "' in button_line
        tooltip = button_line.split(' t "', 1)[1].split('"', 1)[0]
        assert r"\[value" in tooltip
        assert "[value" not in tooltip.replace(r"\[value", "")

    def test_output_dir_knob_has_expression_tooltip(self) -> None:
        gizmo = _generate_gizmo({})
        knob_line = next(line for line in gizmo.splitlines() if "addUserKnob {1 output_dir" in line)
        assert ' t "' in knob_line
        assert r"\[file dirname" in knob_line

    def test_output_dir_tooltip_documents_relative_resolution(self) -> None:
        gizmo = _generate_gizmo({})
        knob_line = next(line for line in gizmo.splitlines() if "addUserKnob {1 output_dir" in line)
        assert "relative path is resolved against the folder containing this .nk script" in knob_line

    def test_output_knob_has_reference_tooltip(self) -> None:
        gizmo = _generate_gizmo_with_output(
            {"caption": {"type": "str", "default_value": "", "mode_allowed_output": True, "ui_options": {}}}
        )
        knob_line = next(line for line in gizmo.splitlines() if "addUserKnob {1 caption_out" in line)
        assert "+DISABLED" in knob_line
        assert ' t "' in knob_line
        assert r"\[value" in knob_line
        assert "caption_out" in knob_line

    def test_numeric_knobs_have_no_tooltip(self) -> None:
        gizmo = _generate_gizmo({"count": {"type": "int", "default_value": 1}})
        knob_line = next(line for line in gizmo.splitlines() if "addUserKnob {3 count" in line)
        assert ' t "' not in knob_line


class TestOutputDirDefaultDocumented:
    """The Run tab must say where outputs land when Output Directory is blank (issue #98)."""

    def test_run_tab_help_text_names_default_output_folder(self) -> None:
        gizmo = _generate_gizmo({})
        help_line = next(line for line in gizmo.splitlines() if "addUserKnob {26 _output_dir_help" in line)
        assert OUTPUTS_DIR_NAME in help_line
        assert ".nk script" in help_line

    def test_help_text_sits_between_output_dir_knob_and_run_button(self) -> None:
        gizmo = _generate_gizmo({})
        lines = gizmo.splitlines()
        knob_idx = next(i for i, line in enumerate(lines) if "addUserKnob {1 output_dir" in line)
        help_idx = next(i for i, line in enumerate(lines) if "addUserKnob {26 _output_dir_help" in line)
        button_idx = next(i for i, line in enumerate(lines) if "addUserKnob {22 run_workflow" in line)
        assert knob_idx < help_idx < button_idx

    def test_output_dir_tooltip_states_blank_default(self) -> None:
        gizmo = _generate_gizmo({})
        knob_line = next(line for line in gizmo.splitlines() if "addUserKnob {1 output_dir" in line)
        assert OUTPUTS_DIR_NAME in knob_line


class TestExpressionLinkButtons:
    """String-family knobs get same-line Link/Copy Link PyScript buttons; other types do not."""

    def test_str_input_gets_link_button(self) -> None:
        gizmo = _generate_gizmo({"folder_path": {"type": "str", "default_value": ""}})
        button_line = next(line for line in gizmo.splitlines() if "addUserKnob {22 _link_folder_path" in line)
        assert 'l "Link..."' in button_line
        assert "-STARTLINE" in button_line
        assert "value this.name" in button_line
        assert "setValue" in button_line
        assert "evaluate" in button_line
        # setExpression returns False on string-family knobs (verified in Nuke 17);
        # the input link button must not attempt it.
        assert "setExpression" not in button_line
        # The expression is stored in the hidden companion knob, not the visible field.
        assert "_gt_expr_folder_path" in button_line

    def test_link_button_has_hidden_expression_knob(self) -> None:
        gizmo = _generate_gizmo({"folder_path": {"type": "str", "default_value": ""}})
        assert 'addUserKnob {1 _gt_expr_folder_path l "" +INVISIBLE}' in gizmo

    def test_knob_changed_code_is_valid_python(self) -> None:
        """The generated callback must parse as Python — guards against string-concat
        traps (e.g. an 'el' fragment relying on the next literal to form 'elif')."""
        ast.parse(_build_knob_changed_code())

    def test_knob_changed_refreshes_links_on_rename(self) -> None:
        gizmo = _generate_gizmo({"folder_path": {"type": "str", "default_value": ""}})
        knob_changed_line = next(line for line in gizmo.splitlines() if line.startswith(" knobChanged"))
        assert "_gt_expr_" in knob_changed_line
        assert '\\"name\\"' in knob_changed_line

    def test_knob_changed_always_present_and_guards_switch_output(self) -> None:
        """The callback is emitted unconditionally; the SwitchOutput branch is
        guarded by nuke.toNode so it is a safe no-op on single-output gizmos."""
        single = _generate_gizmo_with_output(
            {"image": {"type": "ImageUrlArtifact", "default_value": "", "mode_allowed_output": True, "ui_options": {}}}
        )
        single_kc = next(line for line in single.splitlines() if line.startswith(" knobChanged"))
        # active_output handling is always present, but guarded by a SwitchOutput lookup.
        assert "active_output" in single_kc
        assert "SwitchOutput" in single_kc
        assert "_gt_expr_" in single_kc

        multi = _generate_gizmo_with_output(
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
        multi_kc = next(line for line in multi.splitlines() if line.startswith(" knobChanged"))
        assert "active_output" in multi_kc
        assert "SwitchOutput" in multi_kc

    def test_link_button_immediately_follows_its_knob(self) -> None:
        gizmo = _generate_gizmo({"folder_path": {"type": "str", "default_value": ""}})
        lines = gizmo.splitlines()
        knob_idx = next(i for i, line in enumerate(lines) if "addUserKnob {1 folder_path" in line)
        button_idx = next(i for i, line in enumerate(lines) if "addUserKnob {22 _link_folder_path" in line)
        assert button_idx == knob_idx + 1

    def test_int_input_gets_no_link_button(self) -> None:
        gizmo = _generate_gizmo({"count": {"type": "int", "default_value": 1}})
        assert "_link_count" not in gizmo

    def test_dropdown_input_gets_no_link_button(self) -> None:
        gizmo = _generate_gizmo(
            {"mode": {"type": "str", "default_value": "a", "ui_options": {"simple_dropdown": ["a", "b"]}}}
        )
        assert "_link_mode" not in gizmo

    def test_output_dir_gets_link_button(self) -> None:
        gizmo = _generate_gizmo({})
        assert "addUserKnob {22 _link_output_dir" in gizmo

    def test_output_knob_gets_copy_link_button(self) -> None:
        gizmo = _generate_gizmo_with_output(
            {"caption": {"type": "str", "default_value": "", "mode_allowed_output": True, "ui_options": {}}}
        )
        button_line = next(line for line in gizmo.splitlines() if "addUserKnob {22 _copy_caption_out" in line)
        assert 'l "Copy Link"' in button_line
        assert "-STARTLINE" in button_line
        assert "fullName()" in button_line
        assert "clipboard" in button_line
        assert "selectedNodes" in button_line
        assert "setExpression" in button_line

    def test_multiline_input_gets_link_button(self) -> None:
        gizmo = _generate_gizmo({"config": {"type": "JsonArtifact", "default_value": ""}})
        assert "addUserKnob {22 _link_config" in gizmo

    def test_file_input_gets_link_button(self) -> None:
        gizmo = _generate_gizmo({"image": {"type": "ImageUrlArtifact", "default_value": ""}})
        assert "addUserKnob {22 _link_image" in gizmo
