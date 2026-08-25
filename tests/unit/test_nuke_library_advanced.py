"""Tests for the library reload lifecycle's host API bookkeeping.

Not a full test of `NukeLibraryAdvanced`; the publish-workflow wiring already runs inside
Nuke and is exercised there. This covers the two pieces of host API state a reload must not
leave stale: the routing table it hands the engine, and the cached library version.
"""

from __future__ import annotations

from nuke_host_api import library_version
from nuke_host_api.handlers import ROUTES
from nuke_nodes.nuke_library_advanced import NukeLibraryAdvanced


def test_every_route_is_handed_to_the_engine() -> None:
    """A verb the engine is never told about answers nothing, with no error to show for it."""
    assert NukeLibraryAdvanced().get_request_handlers() == list(ROUTES)


def test_library_reload_clears_the_cached_version() -> None:
    """An in-place library upgrade must not keep serving the pre-upgrade version after a reload.

    `before_library_unregistered` also calls `ExecutionBridge.uninstall()` on the module-level
    bridge, which is a safe no-op here since nothing in this test suite installs it.
    """
    library_version.version()  # Prime the cache so clearing it is a real assertion, not a vacuous one.
    assert library_version.version.cache_info().currsize == 1

    NukeLibraryAdvanced().before_library_unregistered(None, None)  # type: ignore[arg-type]

    assert library_version.version.cache_info().currsize == 0
