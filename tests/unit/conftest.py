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

if TYPE_CHECKING:
    from collections.abc import Iterator


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
