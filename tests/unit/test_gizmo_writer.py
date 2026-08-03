"""Tests for gizmo_writer TCL literal escaping."""

from __future__ import annotations

from publish_gizmo.gizmo_writer import _tcl_escape_literal


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
