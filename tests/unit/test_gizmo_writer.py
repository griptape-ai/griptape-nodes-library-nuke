from __future__ import annotations

from publish_gizmo.gizmo_writer import GizmoWriter


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
