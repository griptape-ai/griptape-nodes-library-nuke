"""Shared fixtures for the integration suite.

Ports the isolation and subprocess-boot fixtures from the engine's
``tests/e2e/conftest.py`` and adds ``published_bundle``, which builds and
publishes a real gizmo bundle in-process against ``fixtures/canary/canary_library``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import griptape_nodes.retained_mode.managers.config_manager as config_manager_module
import griptape_nodes.retained_mode.managers.secrets_manager as secrets_manager_module
import pytest
from griptape_nodes.node_library.library_registry import LibraryRegistry
from griptape_nodes.node_library.workflow_registry import WorkflowRegistry
from griptape_nodes.retained_mode.engine import reset_root_engine

from .fixtures.canary.canary_workflow_builder import PublishedBundle, publish_canary_bundle

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def _reset_engine() -> None:
    """Drop the root ``Engine`` and clear its process-global registries."""
    reset_root_engine()
    LibraryRegistry._clear()
    WorkflowRegistry._workflows.clear()


@pytest.fixture(autouse=True)
def _isolated_engine_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Boot each test against empty temp config/secrets and a clean registry."""
    _reset_engine()

    for key in list(os.environ):
        if key.startswith(("GT_CLOUD_", "GTN_CONFIG_", "GTN_ENABLE_", "GTN_NUKE_GIZMO_")):
            monkeypatch.delenv(key, raising=False)
    # Engine managers built during Engine.__init__ mkdir under XDG_DATA_HOME before any test
    # code runs (AgentManager's thread store) and EngineIdentityManager writes engines.json
    # there when it is absent, so an unscoped run scaffolds into the developer's own home.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_config_path = Path(temp_dir) / "griptape_nodes_config.json"
            temp_config_path.write_text(json.dumps({}, indent=2))
            temp_env_path = Path(temp_dir) / ".env"
            temp_env_path.write_text("")
            monkeypatch.setattr(config_manager_module, "USER_CONFIG_PATH", temp_config_path)
            monkeypatch.setattr(secrets_manager_module, "ENV_VAR_PATH", temp_env_path)
            yield
    finally:
        _reset_engine()


@pytest.fixture
def engine_subprocess_env(xdg_scoped_env: Callable[..., dict[str, str]]) -> Callable[..., dict[str, str]]:
    """Return a factory that builds the env for a bundle's ``run_workflow.py`` subprocess."""

    def _build(**overrides: str) -> dict[str, str]:
        env = xdg_scoped_env()
        env.setdefault("GT_CLOUD_API_KEY", "fake-test-key-for-bootstrap")
        env.update(overrides)
        return env

    return _build


@pytest.fixture
def xdg_scoped_env(tmp_path: Path) -> Callable[..., dict[str, str]]:
    """Return a factory for a subprocess env whose XDG directories sit inside this test's tmp_path.

    Everything else is inherited, so a real Nuke launch keeps its licensing (``foundry_LICENSE``),
    display and library-path variables.
    """

    def _build(**overrides: str) -> dict[str, str]:
        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg_config")
        # Both the gizmo's uv venv root and the runner's per-machine scratch (synced_workflows)
        # hang off XDG_DATA_HOME, so without this a run builds a full venv and scaffolds
        # directories into the developer's own home directory, and never cleans them up.
        env["XDG_DATA_HOME"] = str(tmp_path / "xdg_data")
        env.update(overrides)
        return env

    return _build


@pytest.fixture
def published_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., PublishedBundle]:
    """Return a factory that publishes a canary workflow gizmo into a tmp install dir.

    Thin per-test wrapper around ``canary_workflow_builder.publish_canary_bundle``,
    which also backs the real-Nuke wiring check's ``.nk`` fixture generator so both
    drive the same workflow-construction path.
    """

    def _publish(
        *,
        project_id: str | None = None,
    ) -> PublishedBundle:
        return publish_canary_bundle(
            workspace=tmp_path / "workspace",
            install_dir=tmp_path / "install",
            project_id=project_id,
            # monkeypatch.setenv is properly undone on teardown. Can't rely on delenv in
            # _isolated_engine_env's since it records no undo entry for a key that was
            # already absent.
            set_env_var=monkeypatch.setenv,
        )

    return _publish
