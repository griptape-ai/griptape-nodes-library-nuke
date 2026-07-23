"""Tests for run_button._expand_tcl — TCL bracket-expression expansion for knob values."""

from __future__ import annotations

from pathlib import Path

_RUN_BUTTON = Path(__file__).parent.parent.parent / "publish_gizmo" / "run_button.py"


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


class _FakeNode:
    def __init__(self, full_name: str) -> None:
        self._full_name = full_name

    def fullName(self) -> str:  # noqa: N802
        return self._full_name


def _load_expand_tcl(fake_nuke: _FakeNuke):
    """Extract _expand_tcl from run_button.py without running its top-level Nuke code."""
    source = _RUN_BUTTON.read_text(encoding="utf-8")
    lines = source.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("def _expand_tcl("))
    body_lines = []
    for line in lines[start:]:
        if body_lines and line and not line[0].isspace() and not line.startswith("def _expand_tcl"):
            break
        body_lines.append(line)
    ns: dict = {"nuke": fake_nuke}
    exec("\n".join(body_lines), ns)  # noqa: S102
    return ns["_expand_tcl"]


class TestExpandTcl:
    def test_non_str_value_returned_unchanged(self) -> None:
        fake = _FakeNuke()
        expand = _load_expand_tcl(fake)
        assert expand(_FakeNode("Gizmo1"), "count", 5) == 5
        assert expand(_FakeNode("Gizmo1"), "flag", None) is None
        assert fake.calls == []

    def test_str_without_bracket_returned_unchanged(self) -> None:
        fake = _FakeNuke()
        expand = _load_expand_tcl(fake)
        assert expand(_FakeNode("Gizmo1"), "prompt", "hello") == "hello"
        assert fake.calls == []

    def test_str_with_bracket_expanded_via_tcl_value(self) -> None:
        fake = _FakeNuke(result="Gizmo1")
        expand = _load_expand_tcl(fake)
        assert expand(_FakeNode("Gizmo1"), "prompt", "[value this.name]") == "Gizmo1"
        assert fake.calls == [("value", "Gizmo1.prompt")]

    def test_tcl_error_falls_back_to_raw(self) -> None:
        fake = _FakeNuke(error=RuntimeError("bad expression"))
        expand = _load_expand_tcl(fake)
        raw = '[{"a": 1}, {"b": 2}]'
        assert expand(_FakeNode("Gizmo1"), "config", raw) == raw

    def test_empty_expansion_falls_back_to_raw(self) -> None:
        fake = _FakeNuke(result="")
        expand = _load_expand_tcl(fake)
        assert expand(_FakeNode("Gizmo1"), "prompt", "[value this.missing]") == "[value this.missing]"

    def test_nested_node_path_used_in_tcl_call(self) -> None:
        fake = _FakeNuke(result="/out")
        expand = _load_expand_tcl(fake)
        expand(_FakeNode("Group1.wf_v01"), "output_dir", "[file dirname [value root.name]]")
        assert fake.calls == [("value", "Group1.wf_v01.output_dir")]
