"""Tests for gizmo install-path choice computation (NUKE_PATH + ~/.nuke only)."""

from __future__ import annotations

from pathlib import Path

from publish_gizmo.nuke_discovery import (
    GIZMO_INSTALL_CUSTOM,
    compute_gizmo_install_path_choices,
    default_gizmo_path,
    normalize_path_str,
)


class TestComputeGizmoInstallPathChoices:
    def test_always_includes_dot_nuke_first(self, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)
        choices = compute_gizmo_install_path_choices()
        assert choices[0] == normalize_path_str(str(Path.home() / ".nuke"))

    def test_includes_nuke_path_segments(self, monkeypatch, tmp_path) -> None:
        extra = tmp_path / "extra_plugins"
        monkeypatch.setenv("NUKE_PATH", str(extra))
        choices = compute_gizmo_install_path_choices()
        assert normalize_path_str(str(extra)) in choices

    def test_dedups_nuke_path_segment_matching_dot_nuke(self, monkeypatch) -> None:
        dot_nuke = str(Path.home() / ".nuke")
        monkeypatch.setenv("NUKE_PATH", dot_nuke)
        choices = compute_gizmo_install_path_choices()
        assert choices.count(normalize_path_str(dot_nuke)) == 1

    def test_no_nuke_path_returns_only_dot_nuke(self, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)
        choices = compute_gizmo_install_path_choices()
        assert choices == [normalize_path_str(str(Path.home() / ".nuke"))]


class TestDefaultGizmoPath:
    def test_prefers_dot_nuke_even_when_not_first(self) -> None:
        dot_nuke = normalize_path_str(str(Path.home() / ".nuke"))
        candidates = ["/some/other/path", dot_nuke, GIZMO_INSTALL_CUSTOM]
        assert default_gizmo_path(candidates) == dot_nuke

    def test_falls_back_to_first_candidate_when_no_dot_nuke(self) -> None:
        candidates = ["/some/other/path", "/another/path"]
        assert default_gizmo_path(candidates) == "/some/other/path"

    def test_falls_back_to_dot_nuke_when_no_candidates(self) -> None:
        assert default_gizmo_path([]) == normalize_path_str(str(Path.home() / ".nuke"))
