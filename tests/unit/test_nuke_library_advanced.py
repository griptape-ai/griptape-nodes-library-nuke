"""Tests for the library reload lifecycle's host API bookkeeping.

Not a full test of `NukeLibraryAdvanced`; the publish-workflow wiring already runs inside
Nuke and is exercised there. This covers the one piece of host API state a reload must
not leave stale: the cached library version.
"""

from __future__ import annotations

from nuke_host_api.handlers import _library_version
from nuke_nodes.nuke_library_advanced import NukeLibraryAdvanced


def test_library_reload_clears_the_cached_version() -> None:
    """An in-place library upgrade must not keep serving the pre-upgrade version after a reload.

    `before_library_unregistered` also calls `ExecutionBridge.uninstall()` on the module-level
    bridge, which is a safe no-op here since nothing in this test suite installs it.
    """
    _library_version()  # Prime the cache so clearing it is a real assertion, not a vacuous one.
    assert _library_version.cache_info().currsize == 1

    NukeLibraryAdvanced().before_library_unregistered(None, None)  # type: ignore[arg-type]

    assert _library_version.cache_info().currsize == 0
