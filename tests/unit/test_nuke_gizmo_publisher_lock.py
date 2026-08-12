"""Tests for the publisher's uv.lock generation step (best-effort, never fatal)."""

from __future__ import annotations

import ast
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_PUBLISHER = Path(__file__).parent.parent.parent / "publish_gizmo" / "nuke_gizmo_publisher.py"


def _load_func(name: str, ns: dict):
    """Extract one method from the publisher without importing griptape_nodes.

    ast.get_source_segment on a FunctionDef excludes its decorators, so
    staticmethods/classmethods come out as plain functions taking their declared
    params — a classmethod's leading `cls` is supplied by the caller.
    """
    src = _PUBLISHER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            func_src = textwrap.dedent(ast.get_source_segment(src, node) or "")
            exec(func_src, ns)  # noqa: S102
            return ns[name]
    msg = f"{name} not found in nuke_gizmo_publisher.py"
    raise AssertionError(msg)


def _load_write_lockfile(shutil_mod, subprocess_mod, logger):
    """Return _write_lockfile bound to a stub `cls` exposing the real _find_uv."""
    ns: dict = {
        "shutil": shutil_mod,
        "subprocess": subprocess_mod,
        "logger": logger,
        "Path": Path,
        "platform": SimpleNamespace(system=lambda: "Linux"),
    }
    find_uv = _load_func("_find_uv", ns)
    write_lockfile = _load_func("_write_lockfile", ns)
    cls = SimpleNamespace(_find_uv=find_uv)
    return lambda companion_base: write_lockfile(cls, companion_base)


def _lock_writing_run():
    """A subprocess.run stub that succeeds and writes the lockfile uv would write."""

    def _run(cmd, **_kwargs):
        (Path(cmd[3]) / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    return mock.Mock(side_effect=_run)


class TestWriteLockfile:
    def test_runs_uv_lock_with_project(self, tmp_path) -> None:
        run = _lock_writing_run()
        subprocess_mod = SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError)
        fn = _load_write_lockfile(SimpleNamespace(which=lambda _: "/usr/bin/uv"), subprocess_mod, mock.Mock())
        fn(tmp_path)
        cmd = run.call_args[0][0]
        assert cmd[:3] == ["/usr/bin/uv", "lock", "--project"]
        assert cmd[3] == str(tmp_path)

    def test_returns_none_when_lock_written(self, tmp_path) -> None:
        """No reason string means publish reports plain success."""
        subprocess_mod = SimpleNamespace(run=_lock_writing_run(), SubprocessError=subprocess.SubprocessError)
        logger = mock.Mock()
        fn = _load_write_lockfile(SimpleNamespace(which=lambda _: "/usr/bin/uv"), subprocess_mod, logger)
        assert fn(tmp_path) is None
        logger.warning.assert_not_called()

    def test_skips_when_uv_absent(self, tmp_path) -> None:
        run = mock.Mock()
        subprocess_mod = SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError)
        logger = mock.Mock()
        fn = _load_write_lockfile(SimpleNamespace(which=lambda _: None), subprocess_mod, logger)
        reason = fn(tmp_path)
        run.assert_not_called()
        logger.warning.assert_called_once()
        assert reason is not None

    def test_swallows_nonzero_exit(self, tmp_path) -> None:
        run = mock.Mock(return_value=SimpleNamespace(returncode=1, stderr="boom"))
        subprocess_mod = SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError)
        logger = mock.Mock()
        fn = _load_write_lockfile(SimpleNamespace(which=lambda _: "/usr/bin/uv"), subprocess_mod, logger)
        reason = fn(tmp_path)  # must not raise
        logger.warning.assert_called_once()
        assert reason is not None

    def test_swallows_subprocess_error(self, tmp_path) -> None:
        def _raise(*_a, **_k):
            raise OSError("no exec")

        subprocess_mod = SimpleNamespace(run=_raise, SubprocessError=subprocess.SubprocessError)
        logger = mock.Mock()
        fn = _load_write_lockfile(SimpleNamespace(which=lambda _: "/usr/bin/uv"), subprocess_mod, logger)
        reason = fn(tmp_path)  # must not raise
        logger.warning.assert_called_once()
        assert reason is not None

    def test_reports_when_exit_zero_but_no_lock_written(self, tmp_path) -> None:
        """The run button keys off the file, so a silent no-op must not read as success."""
        run = mock.Mock(return_value=SimpleNamespace(returncode=0, stderr=""))
        subprocess_mod = SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError)
        logger = mock.Mock()
        fn = _load_write_lockfile(SimpleNamespace(which=lambda _: "/usr/bin/uv"), subprocess_mod, logger)
        reason = fn(tmp_path)
        assert reason is not None
        logger.warning.assert_called_once()


class TestFindUv:
    """uv resolution mirrors run_button's fallbacks — the engine process may not
    inherit the shell PATH that has uv on it."""

    @staticmethod
    def _find_uv(which, home: Path, system: str = "Linux"):
        ns: dict = {
            "shutil": SimpleNamespace(which=which),
            "Path": SimpleNamespace(home=lambda: home),
            "platform": SimpleNamespace(system=lambda: system),
        }
        return _load_func("_find_uv", ns)

    @staticmethod
    def _touch(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return path

    def test_prefers_path(self, tmp_path) -> None:
        assert self._find_uv(lambda _: "/usr/bin/uv", tmp_path)() == "/usr/bin/uv"

    def test_falls_back_to_griptape_install_dir(self, tmp_path) -> None:
        uv = self._touch(tmp_path / ".local" / "share" / "griptape_nodes" / "bin" / "uv")
        assert self._find_uv(lambda _: None, tmp_path)() == str(uv)

    def test_falls_back_to_local_bin(self, tmp_path) -> None:
        uv = self._touch(tmp_path / ".local" / "bin" / "uv")
        assert self._find_uv(lambda _: None, tmp_path)() == str(uv)

    def test_falls_back_to_cargo_bin(self, tmp_path) -> None:
        uv = self._touch(tmp_path / ".cargo" / "bin" / "uv")
        assert self._find_uv(lambda _: None, tmp_path)() == str(uv)

    def test_uses_exe_suffix_on_windows(self, tmp_path) -> None:
        uv = self._touch(tmp_path / ".local" / "bin" / "uv.exe")
        assert self._find_uv(lambda _: None, tmp_path, system="Windows")() == str(uv)

    def test_returns_none_when_nowhere(self, tmp_path) -> None:
        assert self._find_uv(lambda _: None, tmp_path)() is None
