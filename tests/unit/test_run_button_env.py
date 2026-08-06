"""Tests for run_button's per-machine local-dir + config isolation helpers."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

# run_button.py is exec'd in Nuke's interpreter and references nuke/Qt at module
# scope, so it can't be imported normally.  Import only the pure helpers by
# slicing their source out and exec'ing into a namespace seeded with the stdlib
# modules those helpers reference.
_RUN_BUTTON = Path(__file__).parent.parent.parent / "publish_gizmo" / "run_button.py"


def _func_source(func_name: str) -> str:
    """Return the source lines of a top-level function from run_button.py."""
    source = _RUN_BUTTON.read_text(encoding="utf-8")
    lines = source.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"def {func_name}("))
    body_lines = [lines[start]]
    for line in lines[start + 1 :]:
        if line and not line[0].isspace():
            break
        body_lines.append(line)
    return "\n".join(body_lines)


# Load the pure helpers into one shared namespace so _gizmo_local_dir can call
# _venv_root, without running run_button.py's module-scope Nuke/Qt code.
_NS: dict = {"os": os, "re": re, "hashlib": hashlib}
for _name in ("_venv_root", "_gizmo_local_dir", "_build_child_env"):
    exec(_func_source(_name), _NS)  # noqa: S102

_venv_root = _NS["_venv_root"]
_build_child_env = _NS["_build_child_env"]
_gizmo_local_dir = _NS["_gizmo_local_dir"]


class TestGizmoLocalDir:
    """The per-machine venv/config base dir derivation."""

    def test_under_griptape_nodes_venvs(self) -> None:
        d = _gizmo_local_dir("/mnt/share/griptape/my_workflow", "my_workflow")
        assert "/.local/share/griptape_nodes/venvs/" in d

    def test_is_absolute_and_forward_slashed(self) -> None:
        d = _gizmo_local_dir("C:/share/griptape/my_workflow", "my_workflow")
        assert "\\" not in d
        assert Path(d).is_absolute() or d.startswith(str(Path.home()).replace("\\", "/"))

    def test_name_is_slug_dash_hash8(self) -> None:
        d = _gizmo_local_dir("/mnt/share/griptape/My Workflow!", "My Workflow!")
        name = d.rsplit("/", 1)[-1]
        assert re.fullmatch(r"my-workflow-[0-9a-f]{8}", name), name

    def test_stable_for_same_inputs(self) -> None:
        a = _gizmo_local_dir("/mnt/share/griptape/wf", "wf")
        b = _gizmo_local_dir("/mnt/share/griptape/wf", "wf")
        assert a == b

    def test_distinct_companion_paths_yield_distinct_dirs(self) -> None:
        a = _gizmo_local_dir("/mnt/share/griptape/wf", "wf")
        b = _gizmo_local_dir("/other/share/griptape/wf", "wf")
        assert a != b

    def test_empty_stem_falls_back_to_gizmo_slug(self) -> None:
        d = _gizmo_local_dir("/mnt/share/griptape/wf", "")
        name = d.rsplit("/", 1)[-1]
        assert name.startswith("gizmo-")

    def test_hash_is_case_and_realpath_normalized(self, tmp_path) -> None:
        """Case-variant companion paths for the same dir map to one venv."""
        real = tmp_path / "griptape" / "wf"
        real.mkdir(parents=True)
        a = _gizmo_local_dir(str(real), "wf")
        b = _gizmo_local_dir(os.path.normcase(str(real)), "wf")
        assert a == b

    def test_honors_xdg_data_home(self, monkeypatch) -> None:
        """XDG_DATA_HOME relocates the venv root off a (possibly roaming) home."""
        monkeypatch.setenv("XDG_DATA_HOME", "/scratch/local")
        d = _gizmo_local_dir("/mnt/share/griptape/wf", "wf")
        assert d.startswith("/scratch/local/griptape_nodes/venvs/")


class TestVenvRoot:
    def test_defaults_under_local_share(self, monkeypatch) -> None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        root = _venv_root()
        assert root.endswith(os.path.join("griptape_nodes", "venvs"))
        assert ".local" in root and "share" in root

    def test_honors_xdg_data_home(self, monkeypatch) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", "/scratch/local")
        assert _venv_root() == os.path.join("/scratch/local", "griptape_nodes", "venvs")


class TestBuildChildEnv:
    _LOCAL = "/home/user/.local/share/griptape_nodes/venvs/wf-abcd1234"

    def test_sets_xdg_config_home_under_local_dir(self) -> None:
        """XDG_CONFIG_HOME must point at <local_dir>/.gtn_config, not the companion."""
        env = _build_child_env(self._LOCAL, {})
        assert env["XDG_CONFIG_HOME"] == self._LOCAL + "/.gtn_config"

    def test_sets_uv_project_environment_under_local_dir(self) -> None:
        """UV_PROJECT_ENVIRONMENT redirects uv's venv off the shared companion dir."""
        env = _build_child_env(self._LOCAL, {})
        assert env["UV_PROJECT_ENVIRONMENT"] == self._LOCAL + "/.venv"

    def test_sets_uv_frozen(self) -> None:
        """UV_FROZEN stops uv writing uv.lock back to the shared companion dir."""
        env = _build_child_env(self._LOCAL, {})
        assert env["UV_FROZEN"] == "1"

    def test_config_and_venv_not_in_companion(self) -> None:
        env = _build_child_env(self._LOCAL, {})
        assert "/mnt/share/" not in env["XDG_CONFIG_HOME"]
        assert "/mnt/share/" not in env["UV_PROJECT_ENVIRONMENT"]

    def test_paths_are_forward_slashed(self) -> None:
        """Forward slashes required — Nuke/TCL treats backslashes as escapes."""
        env = _build_child_env(self._LOCAL, {})
        assert "\\" not in env["XDG_CONFIG_HOME"]
        assert "\\" not in env["UV_PROJECT_ENVIRONMENT"]

    def test_preserves_all_base_env_keys(self) -> None:
        """All existing env keys must be present in the child env."""
        base = {"PATH": "/usr/bin", "HOME": "/home/user", "CUSTOM_VAR": "value"}
        env = _build_child_env(self._LOCAL, base)
        for key, value in base.items():
            assert env[key] == value

    def test_does_not_mutate_base_env(self) -> None:
        base = {"PATH": "/usr/bin"}
        original_base = dict(base)
        _build_child_env(self._LOCAL, base)
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
