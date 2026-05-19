"""Tests for nuke_plugin/installer.py — get_plugin_path version resolution."""

from __future__ import annotations

import pytest

from nuke_plugin.installer import _PLUGIN_DIR, get_plugin_path


def test_get_plugin_path_exact_match() -> None:
    path = get_plugin_path(16)
    assert path.exists()
    assert path.name == "nuke16"
    assert path.parent == _PLUGIN_DIR


def test_get_plugin_path_fallback_to_lower() -> None:
    # Nuke 99 doesn't exist; should fall back to the highest available version
    available_versions = sorted(
        int(p.name.replace("nuke", "")) for p in _PLUGIN_DIR.iterdir() if p.is_dir() and p.name.startswith("nuke")
    )
    highest = available_versions[-1]
    path = get_plugin_path(99)
    assert path.exists()
    assert path.name == f"nuke{highest}"


def test_get_plugin_path_exact_nuke15() -> None:
    path = get_plugin_path(15)
    assert path.exists()
    assert path.name == "nuke15"


def test_get_plugin_path_no_match_raises() -> None:
    # Version lower than any available plugin — should raise
    with pytest.raises(RuntimeError, match="No Griptape Annotator plugin available"):
        get_plugin_path(1)


def test_get_plugin_path_returns_path_object() -> None:
    from pathlib import Path

    result = get_plugin_path(16)
    assert isinstance(result, Path)


def test_get_plugin_path_exact_nuke14() -> None:
    path = get_plugin_path(14)
    assert path.exists()
    assert path.name == "nuke14"
