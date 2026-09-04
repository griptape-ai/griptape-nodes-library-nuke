"""Guards which committed files the engine's library-discovery scan can see.

The engine finds libraries by globbing ``griptape[_-]nodes[_-]library.json`` under every
registered directory (``LibraryManager.LIBRARY_CONFIG_GLOB_PATTERN``, applied recursively to a
bounded depth). There is no ignore file and no way to mark a manifest as not-for-installation, so
*any* committed file matching that name becomes a library candidate in the editor of anyone who
registers this checkout -- including files that only exist to be test fixtures.

This repo must therefore expose exactly one such file: the real library manifest at the root.
Test fixtures keep a non-matching name and are materialized under the canonical name into a temp
dir at test time, which works because registration by explicit ``file_path`` does not care what
the file is called.
"""

from __future__ import annotations

from pathlib import Path

# Mirrors LibraryManager.LIBRARY_CONFIG_GLOB_PATTERN in griptape-nodes-engine. Duplicated as a
# literal rather than imported so this guard states the contract it is checking, and keeps holding
# if the engine ever moves the constant.
LIBRARY_CONFIG_GLOB_PATTERN = "griptape[_-]nodes[_-]library.json"

REPO_ROOT = Path(__file__).parents[2]

# The engine's scan skips hidden directories; node_modules is excluded for the same reason the
# Makefile's check/json target excludes it -- vendored third-party trees are not ours to police.
_EXCLUDED_DIR_NAMES = {"node_modules"}


def _discoverable_manifests() -> list[Path]:
    """Every committed file in this repo that the engine's discovery glob would match."""
    return sorted(
        path.relative_to(REPO_ROOT)
        for path in REPO_ROOT.rglob(LIBRARY_CONFIG_GLOB_PATTERN)
        if not any(part.startswith(".") or part in _EXCLUDED_DIR_NAMES for part in path.parts)
    )


class TestLibraryManifestDiscovery:
    """Guards against a fixture manifest becoming visible to the engine's library scan."""

    def test_only_the_root_manifest_is_discoverable(self) -> None:
        assert _discoverable_manifests() == [Path("griptape-nodes-library.json")], (
            "A file matching the engine's library-discovery glob "
            f"({LIBRARY_CONFIG_GLOB_PATTERN}) exists outside the repo root.\n"
            "The engine globs that name under every registered directory and has no way to tell a "
            "fixture from an installable library, so anyone who registers this checkout gets it as "
            "a library candidate -- and a fixture cannot work as one.\n"
            "Give the file a name the glob does not match and materialize it under the canonical "
            "name at test time, the way tests/integration/fixtures/canary does. Registration by "
            "explicit file_path does not require the canonical name."
        )
