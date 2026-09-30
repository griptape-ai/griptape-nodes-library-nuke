"""Guards for the unit suite, which must reach fakes and never the real engine.

Constructing a real ``Engine`` is not a harmless slow path. ConfigManager's default
workspace is ``<cwd>/GriptapeNodes`` and SyncManager mkdirs its scratch directory
unguarded during ``Engine.__init__``, so one stray boot scaffolds a directory into the
repository. The gizmo packager then copies a library's whole source tree into a published
bundle, exempting only ``.venv``, ``__pycache__``, and ``.git``, so that directory
reappears inside the bundle and trips an integration assertion far from the test that
caused it. A developer whose own user config moves the workspace elsewhere never sees any
of it; CI, which has no user config, does.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from nuke_host_api import execution_bridge, flow_run, run_outcome

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _no_detached_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Discard detached tasks bound to a closed test loop."""
    monkeypatch.setattr(flow_run, "_RUN", None)
    monkeypatch.setattr(flow_run, "_RESERVED", False)
    monkeypatch.setattr(flow_run, "_CANCELS", set())
    run_outcome.clear()


class _DroppingEventManager:
    def put_event(self, event: object) -> None:
        pass


class _NoContext:
    def has_current_workflow(self) -> bool:
        return False


class _NoEngine:
    def EventManager(self) -> _DroppingEventManager:  # noqa: N802
        return _DroppingEventManager()

    def ContextManager(self) -> _NoContext:  # noqa: N802
        return _NoContext()


@pytest.fixture(autouse=True)
def _no_real_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every run ends in a published verdict, which would otherwise boot the real engine."""
    monkeypatch.setattr(execution_bridge, "GriptapeNodes", _NoEngine())


@pytest.fixture(autouse=True)
def _no_real_engine_workspace() -> Iterator[None]:
    """Fail the test that booted a real engine, and remove the workspace it scaffolded."""
    workspace = Path.cwd() / "GriptapeNodes"
    existed = workspace.exists()

    yield

    if workspace.exists() and not existed:
        shutil.rmtree(workspace, ignore_errors=True)
        pytest.fail(
            f"This test constructed a real engine: it scaffolded {workspace}. "
            "Unit tests must drive fakes. Check that every fixture touching engine code "
            "tears down while its monkeypatch is still in place."
        )
