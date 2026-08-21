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


def _top_level_source(first_line_prefix: str) -> str:
    """Return a top-level definition from run_button.py, including its continuation lines."""
    source = _RUN_BUTTON.read_text(encoding="utf-8")
    lines = source.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(first_line_prefix))
    body_lines = [lines[start]]
    for line in lines[start + 1 :]:
        # A top-level statement ends at the next line that starts in column 0,
        # except for the closing bracket of a multi-line literal.
        if line and not line[0].isspace():
            if line.startswith(")"):
                body_lines.append(line)
            break
        body_lines.append(line)
    return "\n".join(body_lines)


def _func_source(func_name: str) -> str:
    """Return the source lines of a top-level function from run_button.py."""
    return _top_level_source(f"def {func_name}(")


# Load the pure helpers into one shared namespace so _gizmo_local_dir can call
# _venv_root, without running run_button.py's module-scope Nuke/Qt code.
_NS: dict = {"os": os, "re": re, "hashlib": hashlib}
# _build_child_env reads these module-level constants, so they must be in scope too.
for _const in ("_LEAKED_PYTHON_VARS = (", "_KEEP_PYTHONPATH_VAR = "):
    exec(_top_level_source(_const), _NS)  # noqa: S102
for _name in ("_venv_root", "_gizmo_local_dir", "_has_lockfile", "_build_child_env"):
    exec(_func_source(_name), _NS)  # noqa: S102

_LEAKED_PYTHON_VARS = _NS["_LEAKED_PYTHON_VARS"]

_venv_root = _NS["_venv_root"]
_build_child_env = _NS["_build_child_env"]
_gizmo_local_dir = _NS["_gizmo_local_dir"]
_has_lockfile = _NS["_has_lockfile"]


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

    def test_sets_uv_frozen_when_frozen(self) -> None:
        """UV_FROZEN stops uv writing uv.lock back to the shared companion dir."""
        env = _build_child_env(self._LOCAL, {}, frozen=True)
        assert env["UV_FROZEN"] == "1"

    def test_omits_uv_frozen_when_not_frozen(self) -> None:
        """Without a shipped uv.lock, UV_FROZEN would make uv refuse to run at all."""
        env = _build_child_env(self._LOCAL, {}, frozen=False)
        assert "UV_FROZEN" not in env

    def test_clears_inherited_uv_frozen_when_not_frozen(self) -> None:
        """A site-wide UV_FROZEN export must not reintroduce the no-lockfile failure."""
        env = _build_child_env(self._LOCAL, {"UV_FROZEN": "1", "UV_LOCKED": "1"}, frozen=False)
        assert "UV_FROZEN" not in env
        assert "UV_LOCKED" not in env

    def test_config_and_venv_not_in_companion(self) -> None:
        env = _build_child_env(self._LOCAL, {})
        assert "/mnt/share/" not in env["XDG_CONFIG_HOME"]
        assert "/mnt/share/" not in env["UV_PROJECT_ENVIRONMENT"]

    def test_paths_are_forward_slashed(self) -> None:
        """Forward slashes required — Nuke/TCL treats backslashes as escapes."""
        env = _build_child_env(self._LOCAL, {})
        assert "\\" not in env["XDG_CONFIG_HOME"]
        assert "\\" not in env["UV_PROJECT_ENVIRONMENT"]

    def test_preserves_base_env_keys_outside_the_strip_list(self) -> None:
        """Env keys that aren't interpreter-hijacking must survive untouched."""
        base = {"PATH": "/usr/bin", "HOME": "/home/user", "CUSTOM_VAR": "value"}
        env = _build_child_env(self._LOCAL, base)
        for key, value in base.items():
            assert env[key] == value


class TestChildEnvPythonIsolation:
    """Host Python vars must not shadow the gizmo venv's own site-packages."""

    _LOCAL = "/home/user/.local/share/griptape_nodes/venvs/wf-abcd1234"
    # A wrapper-supplied python3.11 tree, whose older copy of an engine dependency
    # would otherwise be imported ahead of the 3.12 venv's pinned version.
    _WRAPPER_PYTHONPATH = "/opt/wrapper_python_envs/shared/3.11.9/lib/python3.11/site-packages"

    def test_strips_inherited_pythonpath(self) -> None:
        env = _build_child_env(self._LOCAL, {"PYTHONPATH": self._WRAPPER_PYTHONPATH})
        assert "PYTHONPATH" not in env

    def test_strips_pythonhome_and_virtual_env(self) -> None:
        base = {
            "PYTHONHOME": "/opt/wrapper_python_envs/shared/3.11.9",
            "PYTHONEXECUTABLE": "/usr/bin/python3.11",
            "PYTHONSTARTUP": "/etc/pythonstart.py",
            "PYTHONUSERBASE": "/home/user/.local",
            "VIRTUAL_ENV": "/some/other/.venv",
            "CONDA_PREFIX": "/opt/conda",
        }
        env = _build_child_env(self._LOCAL, base)
        for key in base:
            assert key not in env

    def test_strips_uv_python_overrides(self) -> None:
        """An inherited UV_PYTHON would fight the bundle's pinned requires-python."""
        env = _build_child_env(self._LOCAL, {"UV_PYTHON": "3.11", "UV_SYSTEM_PYTHON": "1"})
        assert "UV_PYTHON" not in env
        assert "UV_SYSTEM_PYTHON" not in env

    def test_sets_pythonnousersite(self) -> None:
        """A host user site-packages dir shadows the venv and no env var points at it."""
        env = _build_child_env(self._LOCAL, {})
        assert env["PYTHONNOUSERSITE"] == "1"

    def test_keeps_pythonpath_when_opt_out_set(self) -> None:
        base = {"PYTHONPATH": self._WRAPPER_PYTHONPATH, "GTN_GIZMO_KEEP_PYTHONPATH": "1"}
        env = _build_child_env(self._LOCAL, base)
        assert env["PYTHONPATH"] == self._WRAPPER_PYTHONPATH

    def test_opt_out_still_strips_the_other_vars(self) -> None:
        """The escape hatch is scoped to PYTHONPATH; PYTHONHOME still breaks the venv."""
        base = {"PYTHONHOME": "/opt/py311", "GTN_GIZMO_KEEP_PYTHONPATH": "1"}
        env = _build_child_env(self._LOCAL, base)
        assert "PYTHONHOME" not in env

    def test_falsy_opt_out_still_strips_pythonpath(self) -> None:
        base = {"PYTHONPATH": self._WRAPPER_PYTHONPATH, "GTN_GIZMO_KEEP_PYTHONPATH": "0"}
        env = _build_child_env(self._LOCAL, base)
        assert "PYTHONPATH" not in env

    def test_leaves_ld_library_path_intact(self) -> None:
        """A wrapper env supplies GPU/driver libs this way — stripping it breaks more than it fixes."""
        base = {
            "LD_LIBRARY_PATH": "/opt/nuke/lib:/usr/lib64",
            "DYLD_LIBRARY_PATH": "/opt/lib",
            "PATH": "/usr/bin",
        }
        env = _build_child_env(self._LOCAL, base)
        for key, value in base.items():
            assert env[key] == value

    def test_does_not_mutate_base_env_when_stripping(self) -> None:
        base = {"PYTHONPATH": self._WRAPPER_PYTHONPATH, "PYTHONHOME": "/opt/py311"}
        original = dict(base)
        _build_child_env(self._LOCAL, base)
        assert base == original

    def test_strip_list_matches_the_desktop_app(self) -> None:
        """Kept in sync with griptape-nodes-desktop/src/common/config/env.ts."""
        desktop_vars = {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV"}
        assert desktop_vars <= set(_LEAKED_PYTHON_VARS)

    def test_does_not_mutate_base_env(self) -> None:
        base = {"PATH": "/usr/bin"}
        original_base = dict(base)
        _build_child_env(self._LOCAL, base)
        assert base == original_base

    def test_does_not_mutate_base_env_when_clearing_uv_frozen(self) -> None:
        base = {"PATH": "/usr/bin", "UV_FROZEN": "1"}
        original_base = dict(base)
        _build_child_env(self._LOCAL, base, frozen=False)
        assert base == original_base


class TestHasLockfile:
    """Presence of the companion's uv.lock decides whether the run is frozen."""

    def test_true_when_lock_present(self, tmp_path) -> None:
        (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        assert _has_lockfile(str(tmp_path)) is True

    def test_false_when_lock_absent(self, tmp_path) -> None:
        assert _has_lockfile(str(tmp_path)) is False

    def test_false_when_companion_missing(self, tmp_path) -> None:
        assert _has_lockfile(str(tmp_path / "nope")) is False

    def test_false_when_lock_is_a_directory(self, tmp_path) -> None:
        (tmp_path / "uv.lock").mkdir()
        assert _has_lockfile(str(tmp_path)) is False


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
