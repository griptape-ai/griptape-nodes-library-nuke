"""Tests for the next-steps / notes the publisher reports on a successful publish."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from publish_gizmo.constants import menu_label

_PUBLISHER = Path(__file__).parent.parent.parent / "publish_gizmo" / "nuke_gizmo_publisher.py"


def _load_func(name: str):
    """Extract one staticmethod from the publisher without importing griptape_nodes."""
    src = _PUBLISHER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            ns: dict = {"Path": Path, "menu_label": menu_label}
            exec(textwrap.dedent(ast.get_source_segment(src, node) or ""), ns)  # noqa: S102
            return ns[name]
    msg = f"{name} not found in nuke_gizmo_publisher.py"
    raise AssertionError(msg)


def _steps(**overrides) -> list[str]:
    kwargs = {
        "workflow_stem": "my_workflow",
        "install_dir": Path("/home/user/.nuke"),
        "version": 1,
        "published_count": 1,
        "first_time_setup": False,
    }
    kwargs.update(overrides)
    return _load_func("_build_next_steps")(**kwargs)


def _notes(**overrides) -> list[str]:
    kwargs = {"install_dir": Path("/home/user/.nuke"), "install_dir_created": False, "lock_error": None}
    kwargs.update(overrides)
    return _load_func("_build_publish_notes")(**kwargs)


class TestNextSteps:
    def test_names_the_menu_entry_the_generated_menu_will_create(self) -> None:
        """The artist has to find the node by label, so the label has to be the real one."""
        assert any("Nodes > Griptape > My Workflow" in step for step in _steps())

    def test_says_not_to_open_the_gizmo_directly(self) -> None:
        """Publish reports a .gizmo path, which reads like something to double-click."""
        assert any("don't open it directly" in step for step in _steps())

    def test_first_publish_asks_for_a_restart(self) -> None:
        """init.py gained the plugin path, and Nuke reads init.py only at startup."""
        steps = _steps(first_time_setup=True)
        assert "Restart Nuke" in steps[0]
        assert "init.py" in steps[0]

    def test_republish_does_not_ask_for_a_restart(self) -> None:
        assert not any("Restart Nuke" in step for step in _steps())

    def test_first_publish_step_says_the_restart_is_per_install_directory(self) -> None:
        """Not once ever: a later publish to a different install dir needs its own restart."""
        step = _steps(first_time_setup=True)[0]
        assert "this install directory" in step
        assert "Later publishes here need no restart." in step

    def test_republish_mentions_the_refresh_fallback(self) -> None:
        """The watcher misses changes on network mounts; the menu command is the way out."""
        steps = _steps()
        assert any("Refresh Griptape Gizmos" in step for step in steps)
        assert any("network mount" in step for step in steps)

    def test_republish_still_offers_a_restart_when_there_is_no_griptape_menu(self) -> None:
        """A session predating the very first publish here has no menu to refresh.

        first_time_setup is False on that publish -- the marker was written by the earlier
        one -- so pointing only at Refresh Griptape Gizmos would name a command that
        session never loaded.
        """
        assert any("no" in step and "Griptape menu" in step and "restart Nuke" in step for step in _steps())

    def test_first_publish_omits_the_refresh_fallback(self) -> None:
        """Nothing to refresh before the restart that first loads the plugin path."""
        assert not any("Refresh Griptape Gizmos" in step for step in _steps(first_time_setup=True))

    def test_single_version_points_at_a_flat_entry(self) -> None:
        assert any("Nodes > Griptape > My Workflow." in step for step in _steps())

    def test_multiple_versions_point_into_the_version_submenu(self) -> None:
        """The generated menu nests versions once more than one gizmo exists."""
        assert any("Nodes > Griptape > My Workflow > v2" in step for step in _steps(version=2, published_count=2))

    def test_run_step_names_the_run_button_knob(self) -> None:
        assert any("Run Workflow" in step for step in _steps())


class TestPublishNotes:
    def test_empty_on_a_clean_publish(self) -> None:
        assert _notes() == []

    def test_reports_a_created_install_dir(self) -> None:
        notes = _notes(install_dir_created=True)
        assert len(notes) == 1
        assert "/home/user/.nuke" in notes[0]

    def test_reports_an_unpinned_lockfile_with_its_reason(self) -> None:
        notes = _notes(lock_error="uv not found")
        assert len(notes) == 1
        assert "uv not found" in notes[0]

    def test_lock_failure_is_a_note_not_a_step(self) -> None:
        """It's a caveat about what was published, not an action the artist takes next."""
        assert not any("uv" in step for step in _steps())
