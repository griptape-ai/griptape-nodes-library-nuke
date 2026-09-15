"""Host API bookkeeping across library reloads."""

from __future__ import annotations

from nuke_host_api import host_claim, library_version
from nuke_host_api.handlers import ROUTES
from nuke_nodes.nuke_library_advanced import NukeLibraryAdvanced


def test_every_route_is_handed_to_the_engine() -> None:
    assert NukeLibraryAdvanced().get_request_handlers() == list(ROUTES)


def test_library_reload_clears_the_cached_version() -> None:
    """A reload must not retain the previous manifest version."""
    library_version.version()  # Prime the cache so clearing it is a real assertion, not a vacuous one.
    assert library_version.version.cache_info().currsize == 1

    NukeLibraryAdvanced().before_library_unregistered(None, None)  # type: ignore[arg-type]

    assert library_version.version.cache_info().currsize == 0


def test_library_reload_releases_the_host_claim() -> None:
    """A reload forces every host to reconnect, so a retained claim would lock the engine."""
    host_claim.claim("Nuke shot_040")

    NukeLibraryAdvanced().before_library_unregistered(None, None)  # type: ignore[arg-type]

    assert host_claim.held() is None
