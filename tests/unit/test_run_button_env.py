"""Tests for run_button._build_child_env — the bundle config isolation helper."""

from __future__ import annotations

from pathlib import Path

# run_button.py is exec'd in Nuke's interpreter and references nuke/Qt at module
# scope, so it can't be imported normally.  Import only the pure helper by
# inserting the source dir and importing the function via exec into a namespace.
_RUN_BUTTON = Path(__file__).parent.parent.parent / "publish_gizmo" / "run_button.py"


def _load_build_child_env():
    """Extract _build_child_env from run_button.py without running its top-level Nuke code."""
    source = _RUN_BUTTON.read_text(encoding="utf-8")
    # Isolate just the function definition.
    lines = source.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("def _build_child_env("))
    # Collect lines until the next top-level definition or blank-then-non-blank pair.
    body_lines = []
    for line in lines[start:]:
        if body_lines and line and not line[0].isspace() and not line.startswith("def _build_child_env"):
            break
        body_lines.append(line)
    ns: dict = {}
    exec("\n".join(body_lines), ns)  # noqa: S102
    return ns["_build_child_env"]


_build_child_env = _load_build_child_env()


class TestBuildChildEnv:
    def test_sets_xdg_config_home_inside_bundle(self) -> None:
        """XDG_CONFIG_HOME must point at <companion>/.gtn_config."""
        env = _build_child_env("/some/bundle", {})
        assert env["XDG_CONFIG_HOME"] == "/some/bundle/.gtn_config"

    def test_xdg_config_home_is_absolute(self) -> None:
        env = _build_child_env("/abs/path/bundle", {})
        assert Path(env["XDG_CONFIG_HOME"]).is_absolute()

    def test_xdg_config_home_uses_forward_slashes(self) -> None:
        """Forward slashes required — Nuke/TCL treats backslashes as escapes."""
        env = _build_child_env("C:/Users/jadan/.nuke/griptape/myWorkflow", {})
        assert "\\" not in env["XDG_CONFIG_HOME"]

    def test_preserves_all_base_env_keys(self) -> None:
        """All existing env keys must be present in the child env."""
        base = {"PATH": "/usr/bin", "HOME": "/home/user", "CUSTOM_VAR": "value"}
        env = _build_child_env("/bundle", base)
        for key, value in base.items():
            assert env[key] == value

    def test_does_not_mutate_base_env(self) -> None:
        base = {"PATH": "/usr/bin"}
        original_base = dict(base)
        _build_child_env("/bundle", base)
        assert base == original_base


class TestRunnerXdgConfigHomeImportOrder:
    """Guard the import-ordering invariant: XDG_CONFIG_HOME must be set before
    any griptape_nodes import so the engine's config path is frozen correctly."""

    def test_xdg_config_home_set_before_griptape_import(self) -> None:
        """The env guard block must appear before the first 'from griptape_nodes' line."""
        source = (Path(__file__).parent.parent.parent / "publish_gizmo" / "nuke_workflow_runner.py").read_text(
            encoding="utf-8"
        )
        lines = source.splitlines()

        xdg_line = next(
            (i for i, line in enumerate(lines) if "XDG_CONFIG_HOME" in line and "os.environ" in line),
            None,
        )
        griptape_line = next(
            (i for i, line in enumerate(lines) if line.startswith("from griptape_nodes")),
            None,
        )

        assert xdg_line is not None, "XDG_CONFIG_HOME guard not found in nuke_workflow_runner.py"
        assert griptape_line is not None, "No 'from griptape_nodes' import found in nuke_workflow_runner.py"
        assert xdg_line < griptape_line, (
            f"XDG_CONFIG_HOME guard (line {xdg_line + 1}) must precede "
            f"first griptape_nodes import (line {griptape_line + 1})"
        )

    def test_runner_respects_parent_xdg_config_home(self) -> None:
        """If XDG_CONFIG_HOME is already set by the parent, the runner must not overwrite it."""
        import os

        sentinel = "/parent/set/config/home"
        original = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = sentinel
        try:
            # Re-exec only the guard block from the runner.
            source = (Path(__file__).parent.parent.parent / "publish_gizmo" / "nuke_workflow_runner.py").read_text(
                encoding="utf-8"
            )
            lines = source.splitlines()
            # Find the guard block: `if not os.environ.get("XDG_CONFIG_HOME"):` and its body.
            start = next(i for i, line in enumerate(lines) if 'os.environ.get("XDG_CONFIG_HOME")' in line)
            block_lines = []
            for line in lines[start:]:
                if block_lines and line and not line[0].isspace():
                    break
                block_lines.append(line)
            exec("\n".join(block_lines), {"os": os, "Path": Path})  # noqa: S102
            assert os.environ["XDG_CONFIG_HOME"] == sentinel, (
                "Runner must not overwrite parent-provided XDG_CONFIG_HOME"
            )
        finally:
            if original is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = original
