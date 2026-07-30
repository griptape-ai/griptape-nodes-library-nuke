"""Tests for tcl_utils._expand_tcl — TCL bracket-expression expansion for knob values."""

from __future__ import annotations

import pytest

from publish_gizmo import tcl_utils
from publish_gizmo.tcl_utils import _expand_tcl


class _FakeNuke:
    def __init__(self, result: str | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple] = []

    def tcl(self, *args):
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result


class _FakeExprKnob:
    def __init__(self, text: str, evaluated: str | None = None, error: Exception | None = None) -> None:
        self._text = text
        self._evaluated = evaluated
        self._error = error

    def getText(self) -> str:  # noqa: N802
        return self._text

    def evaluate(self) -> str | None:
        if self._error is not None:
            raise self._error
        return self._evaluated


class _FakeNode:
    def __init__(self, full_name: str, expr_knobs: dict | None = None) -> None:
        self._full_name = full_name
        self._expr_knobs = expr_knobs or {}

    def fullName(self) -> str:  # noqa: N802
        return self._full_name

    def knob(self, name: str):
        return self._expr_knobs.get(name)


@pytest.fixture
def fake_nuke(monkeypatch: pytest.MonkeyPatch) -> _FakeNuke:
    """Install a fake ``nuke`` on the tcl_utils module for the duration of a test."""
    fake = _FakeNuke()
    monkeypatch.setattr(tcl_utils, "nuke", fake)
    return fake


class TestExpandTcl:
    def test_non_str_value_returned_unchanged(self, fake_nuke: _FakeNuke) -> None:
        assert _expand_tcl(_FakeNode("Gizmo1"), "count", 5) == 5
        assert _expand_tcl(_FakeNode("Gizmo1"), "flag", None) is None
        assert fake_nuke.calls == []

    def test_str_without_bracket_returned_unchanged(self, fake_nuke: _FakeNuke) -> None:
        assert _expand_tcl(_FakeNode("Gizmo1"), "prompt", "hello") == "hello"
        assert fake_nuke.calls == []

    def test_str_with_bracket_expanded_via_tcl_value(self, fake_nuke: _FakeNuke) -> None:
        fake_nuke.result = "Gizmo1"
        assert _expand_tcl(_FakeNode("Gizmo1"), "prompt", "[value this.name]") == "Gizmo1"
        assert fake_nuke.calls == [("value", "Gizmo1.prompt")]

    def test_tcl_error_falls_back_to_raw(self, fake_nuke: _FakeNuke) -> None:
        fake_nuke.error = RuntimeError("bad expression")
        raw = '[{"a": 1}, {"b": 2}]'
        assert _expand_tcl(_FakeNode("Gizmo1"), "config", raw) == raw

    def test_empty_tcl_expansion_passes_through(self, fake_nuke: _FakeNuke) -> None:
        """A hand-typed expression evaluating to "" returns "" (not the raw text)."""
        fake_nuke.result = ""
        assert _expand_tcl(_FakeNode("Gizmo1"), "prompt", "[value this.missing]") == ""

    def test_nested_node_path_used_in_tcl_call(self, fake_nuke: _FakeNuke) -> None:
        fake_nuke.result = "/out"
        _expand_tcl(_FakeNode("Group1.wf_v01"), "output_dir", "[file dirname [value root.name]]")
        assert fake_nuke.calls == [("value", "Group1.wf_v01.output_dir")]

    def test_stored_link_expression_takes_precedence(self, fake_nuke: _FakeNuke) -> None:
        fake_nuke.result = "should-not-be-used"
        node = _FakeNode("Gizmo1", {"_gt_expr_prompt": _FakeExprKnob("[value this.name]", evaluated="Gizmo1")})
        assert _expand_tcl(node, "prompt", "stale display text") == "Gizmo1"
        assert fake_nuke.calls == []

    def test_empty_stored_expression_returns_empty(self, fake_nuke: _FakeNuke) -> None:
        """A stored link that evaluates to "" returns "" — not the stale display text."""
        node = _FakeNode("Gizmo1", {"_gt_expr_prompt": _FakeExprKnob("[value root.name]", evaluated="")})
        assert _expand_tcl(node, "prompt", "stale display text") == ""
        assert fake_nuke.calls == []

    def test_blank_stored_expression_falls_through_to_raw(self, fake_nuke: _FakeNuke) -> None:
        """No stored expression text at all -> fall through to the raw value."""
        node = _FakeNode("Gizmo1", {"_gt_expr_prompt": _FakeExprKnob("")})
        assert _expand_tcl(node, "prompt", "typed text") == "typed text"

    def test_failing_stored_expression_falls_through(self, fake_nuke: _FakeNuke) -> None:
        node = _FakeNode("Gizmo1", {"_gt_expr_prompt": _FakeExprKnob("[bad", error=RuntimeError("bad expression"))})
        assert _expand_tcl(node, "prompt", "typed text") == "typed text"
