"""Root-level pytest configuration shared by the unit and integration suites.

``publish_gizmo/nuke_workflow_runner.py`` mutates ``os.environ["XDG_CONFIG_HOME"]``
at *module import time* as a fallback for standalone invocations (see that
module's own guard block for why it can't be moved into a function). Several
test modules import that module during collection, so without this guard,
whichever value the runner happens to set leaks into every later test in the
session.

This module is imported by pytest before collection starts -- and therefore
before any test module (and any of their imports) run -- so it is the
earliest reliable point to snapshot the true pre-session value of
``XDG_CONFIG_HOME``. The autouse fixture below then restores that snapshot
before every test runs, so each test observes the original value regardless
of what happened during collection, or what an earlier test (or a lazy
in-test import of the runner) did to it.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

_ORIGINAL_XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME")


@pytest.fixture(scope="session")
def original_xdg_config_home() -> str | None:
    """Return the pre-session ``XDG_CONFIG_HOME`` snapshot taken before test collection."""
    return _ORIGINAL_XDG_CONFIG_HOME


@pytest.fixture(autouse=True)
def _restore_xdg_config_home() -> Iterator[None]:
    """Reset ``XDG_CONFIG_HOME`` to its pre-session value before every test.

    Guards against ``nuke_workflow_runner.py``'s module-scope fallback, which
    otherwise leaks into every later test in the session once any module
    imports the runner during collection.
    """
    if _ORIGINAL_XDG_CONFIG_HOME is None:
        os.environ.pop("XDG_CONFIG_HOME", None)
    else:
        os.environ["XDG_CONFIG_HOME"] = _ORIGINAL_XDG_CONFIG_HOME
    yield
