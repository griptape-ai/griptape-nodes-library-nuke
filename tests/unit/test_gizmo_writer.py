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
