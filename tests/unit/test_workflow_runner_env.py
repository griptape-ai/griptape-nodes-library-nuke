"""Tests for how the bundled .env is applied to the gizmo subprocess environment.

The runner cannot be imported directly (it pulls in griptape_nodes and mutates
XDG_CONFIG_HOME at import time), so _load_bundled_env is extracted from source.
"""

from __future__ import annotations

import ast
import os
import textwrap
from pathlib import Path

import pytest
from dotenv import dotenv_values

_RUNNER = Path(__file__).parent.parent.parent / "publish_gizmo" / "nuke_workflow_runner.py"

_API_KEY = "GT_CLOUD_API_KEY"


def _load_bundled_env_fn():
    src = _RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_load_bundled_env":
            func_src = textwrap.dedent(ast.get_source_segment(src, node) or "")
            ns: dict = {"os": os, "dotenv_values": dotenv_values, "Path": Path}
            exec(func_src, ns)  # noqa: S102
            return ns["_load_bundled_env"]
    msg = "_load_bundled_env not found in nuke_workflow_runner.py"
    raise AssertionError(msg)


@pytest.fixture
def load_bundled_env():
    return _load_bundled_env_fn()


@pytest.fixture
def env_file(tmp_path):
    def _write(contents: str) -> Path:
        path = tmp_path / ".env"
        path.write_text(contents, encoding="utf-8")
        return path

    return _write


@pytest.fixture(autouse=True)
def _isolate_environ(monkeypatch):
    monkeypatch.delenv(_API_KEY, raising=False)


def test_blank_parent_value_does_not_shadow_the_bundled_key(load_bundled_env, env_file, monkeypatch) -> None:
    """The reported failure: a blank in Nuke's environment hid a valid bundled key.

    load_dotenv(override=False) defers on key presence, so an empty-but-present
    variable counted as configured and the published gizmo failed as if no
    credential existed.
    """
    monkeypatch.setenv(_API_KEY, "")
    load_bundled_env(env_file(f"{_API_KEY}=realkey123\n"))
    assert os.environ[_API_KEY] == "realkey123"


def test_meaningful_parent_value_still_wins(load_bundled_env, env_file, monkeypatch) -> None:
    """A farm job supplying its own credential must not be clobbered by the bundle."""
    monkeypatch.setenv(_API_KEY, "per-job-key")
    load_bundled_env(env_file(f"{_API_KEY}=bundled\n"))
    assert os.environ[_API_KEY] == "per-job-key"


def test_absent_parent_value_takes_the_bundled_key(load_bundled_env, env_file) -> None:
    load_bundled_env(env_file(f"{_API_KEY}=bundled\n"))
    assert os.environ[_API_KEY] == "bundled"


def test_blank_bundled_value_is_not_exported(load_bundled_env, env_file) -> None:
    """Bundles published before blanks were filtered out still carry them.

    Exporting one would put a blank in os.environ, which the engine's secret
    lookup checks first and reads as a configured empty credential.
    """
    load_bundled_env(env_file(f'{_API_KEY}=""\n'))
    assert _API_KEY not in os.environ


def test_quoted_values_are_parsed_not_taken_literally(load_bundled_env, env_file) -> None:
    load_bundled_env(env_file(f'{_API_KEY}="key with spaces"\n'))
    assert os.environ[_API_KEY] == "key with spaces"
