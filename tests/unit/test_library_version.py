"""Tests for the library version read.

protocol.py's old LIBRARY_VERSION constant drifted from the manifest; this reads it live.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from nuke_host_api import library_version


@pytest.fixture(autouse=True)
def _clear_cache() -> Any:
    """Isolate each read, since the value is cached for the process lifetime."""
    library_version.reset()
    yield
    library_version.reset()


def test_reads_the_shipped_version_from_the_manifest() -> None:
    assert library_version.version() == "0.3.0"


def test_the_read_is_cached() -> None:
    library_version.version()
    assert library_version.version.cache_info().currsize == 1


def test_reset_drops_the_cached_read() -> None:
    """An in-place library upgrade must not keep serving the pre-upgrade version."""
    library_version.version()

    library_version.reset()

    assert library_version.version.cache_info().currsize == 0


def test_degrades_to_unknown_when_the_manifest_is_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(library_version, "MANIFEST_PATH", tmp_path / "does_not_exist.json")
    assert library_version.version() == "unknown"


def test_degrades_to_unknown_when_the_manifest_is_malformed_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    malformed = tmp_path / "griptape-nodes-library.json"
    malformed.write_text("{not valid json")
    monkeypatch.setattr(library_version, "MANIFEST_PATH", malformed)

    assert library_version.version() == "unknown"


def test_degrades_to_unknown_when_the_manifest_has_no_library_version_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    missing_key = tmp_path / "griptape-nodes-library.json"
    missing_key.write_text(json.dumps({"metadata": {}}))
    monkeypatch.setattr(library_version, "MANIFEST_PATH", missing_key)

    assert library_version.version() == "unknown"
