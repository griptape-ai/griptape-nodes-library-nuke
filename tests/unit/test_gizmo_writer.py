"""Tests for gizmo_writer TCL literal escaping and knob emission."""

from __future__ import annotations

from publish_gizmo.gizmo_writer import GizmoWriter, _tcl_escape_literal


class TestTclEscapeLiteral:
    def test_plain_text_is_noop(self) -> None:
        assert _tcl_escape_literal("hello world") == "hello world"

    def test_open_bracket_escaped(self) -> None:
        assert _tcl_escape_literal("[value this.name]") == r"\[value this.name]"

    def test_close_bracket_not_escaped(self) -> None:
        assert _tcl_escape_literal("a]b") == "a]b"

    def test_quote_escaped(self) -> None:
        assert _tcl_escape_literal('say "hi"') == r"say \"hi\""

    def test_backslash_doubled(self) -> None:
        assert _tcl_escape_literal("C:\\path") == "C:\\\\path"

    def test_dollar_escaped(self) -> None:
        assert _tcl_escape_literal("$var") == r"\$var"

    def test_backslash_before_bracket_escapes_both(self) -> None:
        assert _tcl_escape_literal(r"\[x]") == r"\\\[x]"

    def test_newline_preserved(self) -> None:
        assert _tcl_escape_literal("line1\nline2") == "line1\nline2"


class TestAddTextKnob:
    def test_text_knob_emits_type_26_with_text_content(self) -> None:
        w = GizmoWriter()
        w.add_text_knob("_help", text="Saved next to the script.")
        line = w.render().splitlines()[0]
        assert line.startswith(" addUserKnob {26 _help")
        assert 'l ""' in line
        assert 'T "Saved next to the script."' in line
        assert "+STARTLINE" in line

    def test_text_knob_escapes_tcl_specials(self) -> None:
        w = GizmoWriter()
        w.add_text_knob("_help", text='use [value root.name] or "quotes"')
        line = w.render().splitlines()[0]
        assert r"\[value root.name]" in line
        assert r"\"quotes\"" in line


class TestNumericKnobDefaults:
    """Numeric knobs must never emit a value line with an empty/blank value.

    A dangling `` knob_name`` line makes Nuke's TCL parser read the next line's
    leading ``addUserKnob`` token as the knob's expression, producing an
    "Expression: addUserKnob -> Nothing is named addUserKnob" error and leaving
    the knob stuck at 0.
    """

    def test_double_knob_skips_empty_string_default(self) -> None:
        w = GizmoWriter()
        w.add_double_knob("guidance", "Guidance Scale", default="")
        w.add_string_knob("prompt", "Prompt", default="hello")
        assert " guidance \n" not in w.render()
        assert " guidance\n" not in w.render()

    def test_int_knob_skips_empty_string_default(self) -> None:
        w = GizmoWriter()
        w.add_int_knob("steps", "Steps", default="")
        assert " steps \n" not in w.render()
        assert " steps\n" not in w.render()

    def test_double_knob_skips_none_default(self) -> None:
        w = GizmoWriter()
        w.add_double_knob("guidance", "Guidance Scale", default=None)
        assert " guidance \n" not in w.render()
        assert " guidance\n" not in w.render()

    def test_double_knob_keeps_zero_default(self) -> None:
        w = GizmoWriter()
        w.add_double_knob("guidance", "Guidance Scale", default=0)
        assert " guidance 0\n" in w.render()

    def test_double_knob_keeps_nonzero_default(self) -> None:
        w = GizmoWriter()
        w.add_double_knob("guidance", "Guidance Scale", default=3.5)
        assert " guidance 3.5\n" in w.render()

    def test_int_knob_keeps_zero_default(self) -> None:
        w = GizmoWriter()
        w.add_int_knob("steps", "Steps", default=0)
        assert " steps 0\n" in w.render()

    def test_empty_default_does_not_swallow_following_knob(self) -> None:
        """The line after an empty-default numeric knob is still a valid addUserKnob."""
        w = GizmoWriter()
        w.add_double_knob("guidance", "Guidance Scale", default="")
        w.add_string_knob("prompt", "Prompt", default="hello")
        lines = w.render().splitlines()
        guidance_idx = next(i for i, line in enumerate(lines) if "guidance" in line)
        assert lines[guidance_idx + 1].strip().startswith("addUserKnob")
