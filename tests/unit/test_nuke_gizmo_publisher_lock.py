"""Tests for the publisher's uv.lock generation step (best-effort, never fatal)."""

from __future__ import annotations

import ast
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_PUBLISHER = Path(__file__).parent.parent.parent / "publish_gizmo" / "nuke_gizmo_publisher.py"


def _load_write_lockfile(shutil_mod, subprocess_mod, logger):
    """Extract _write_lockfile from the publisher without importing griptape_nodes."""
    src = _PUBLISHER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_write_lockfile":
            func_src = textwrap.dedent(ast.get_source_segment(src, node) or "")
            ns: dict = {"shutil": shutil_mod, "subprocess": subprocess_mod, "logger": logger, "Path": Path}
            exec(func_src, ns)  # noqa: S102
            return ns["_write_lockfile"]
    msg = "_write_lockfile not found in nuke_gizmo_publisher.py"
    raise AssertionError(msg)


class TestWriteLockfile:
    def test_runs_uv_lock_with_project(self, tmp_path) -> None:
        run = mock.Mock(return_value=SimpleNamespace(returncode=0, stderr=""))
        subprocess_mod = SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError)
        fn = _load_write_lockfile(SimpleNamespace(which=lambda _: "/usr/bin/uv"), subprocess_mod, mock.Mock())
        fn(tmp_path)
        cmd = run.call_args[0][0]
        assert cmd[:3] == ["/usr/bin/uv", "lock", "--project"]
        assert cmd[3] == str(tmp_path)

    def test_skips_when_uv_absent(self, tmp_path) -> None:
        run = mock.Mock()
        subprocess_mod = SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError)
        logger = mock.Mock()
        fn = _load_write_lockfile(SimpleNamespace(which=lambda _: None), subprocess_mod, logger)
        fn(tmp_path)
        run.assert_not_called()
        logger.warning.assert_called_once()

    def test_swallows_nonzero_exit(self, tmp_path) -> None:
        run = mock.Mock(return_value=SimpleNamespace(returncode=1, stderr="boom"))
        subprocess_mod = SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError)
        logger = mock.Mock()
        fn = _load_write_lockfile(SimpleNamespace(which=lambda _: "/usr/bin/uv"), subprocess_mod, logger)
        fn(tmp_path)  # must not raise
        logger.warning.assert_called_once()

    def test_swallows_subprocess_error(self, tmp_path) -> None:
        def _raise(*_a, **_k):
            raise OSError("no exec")

        subprocess_mod = SimpleNamespace(run=_raise, SubprocessError=subprocess.SubprocessError)
        logger = mock.Mock()
        fn = _load_write_lockfile(SimpleNamespace(which=lambda _: "/usr/bin/uv"), subprocess_mod, logger)
        fn(tmp_path)  # must not raise
        logger.warning.assert_called_once()
