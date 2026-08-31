"""Tests for the simplified Nuke publish dialog options (no Nuke-executable dropdown)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from griptape_nodes.retained_mode.events.workflow_events import GetPublishOptionsRequest

from publish_gizmo.nuke_discovery import GIZMO_INSTALL_CUSTOM, normalize_path_str
from publish_gizmo.nuke_publish_options import get_nuke_publish_options


def _request(current_selections: dict | None = None) -> GetPublishOptionsRequest:
    return GetPublishOptionsRequest(
        workflow_name="my_workflow", publisher_name="nuke", current_selections=current_selections
    )


@patch("publish_gizmo.nuke_publish_options._find_nuke_start_flow_node", return_value=None)
class TestGetNukePublishOptions:
    def test_no_nuke_installation_field(self, _mock_find, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)
        result = get_nuke_publish_options(_request({}))
        names = [f.name for f in result.fields]
        assert "nuke" not in names

    def test_gizmo_install_path_field_has_no_dependency(self, _mock_find, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)
        result = get_nuke_publish_options(_request({}))
        gizmo_field = next(f for f in result.fields if f.name == "gizmo_install_path")
        assert gizmo_field.depends_on is None

    def test_default_choice_is_dot_nuke(self, _mock_find, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)
        result = get_nuke_publish_options(_request({}))
        gizmo_field = next(f for f in result.fields if f.name == "gizmo_install_path")
        assert gizmo_field.default_value == normalize_path_str(str(Path.home() / ".nuke"))
        assert gizmo_field.choices is not None
        assert gizmo_field.choices[0] == normalize_path_str(str(Path.home() / ".nuke"))
        assert gizmo_field.choices[-1] == GIZMO_INSTALL_CUSTOM

    def test_custom_gizmo_path_hidden_unless_custom_selected(self, _mock_find, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)
        result = get_nuke_publish_options(_request({"gizmo_install_path": GIZMO_INSTALL_CUSTOM}))
        custom_field = next(f for f in result.fields if f.name == "custom_gizmo_path")
        assert custom_field.hidden is False

        result = get_nuke_publish_options(_request({}))
        custom_field = next(f for f in result.fields if f.name == "custom_gizmo_path")
        assert custom_field.hidden is True

    def test_restores_from_saved_publish_config_with_stale_nuke_key(self, _mock_find, monkeypatch) -> None:
        """Old publish_config blobs saved before this simplification may still carry
        a 'nuke' key — restoring them must not error even though the field is gone."""
        monkeypatch.delenv("NUKE_PATH", raising=False)
        start_flow = MagicMock()
        start_flow.metadata = {
            "publish_config": {
                "nuke": "/Applications/Nuke16.0v7",
                "gizmo_install_path": normalize_path_str(str(Path.home() / ".nuke")),
                "custom_gizmo_path": None,
                "gizmo_path": "/some/gizmo/path",
                "version": 2,
            }
        }
        with patch("publish_gizmo.nuke_publish_options._find_nuke_start_flow_node", return_value=start_flow):
            result = get_nuke_publish_options(_request(None))

        names = [f.name for f in result.fields]
        assert "nuke" not in names
        assert "update_mode" in names
        gizmo_field = next(f for f in result.fields if f.name == "gizmo_install_path")
        assert gizmo_field.default_value == normalize_path_str(str(Path.home() / ".nuke"))

    def test_saved_relative_custom_path_is_shown_absolute(self, _mock_find, monkeypatch) -> None:
        """Anchored to the workspace, since that is the base the file picker used."""
        monkeypatch.delenv("NUKE_PATH", raising=False)
        with patch("publish_gizmo.nuke_publish_options.GriptapeNodes") as griptape_nodes:
            griptape_nodes.ConfigManager.return_value.workspace_path = Path("/home/user/workspace")
            result = get_nuke_publish_options(
                _request({"gizmo_install_path": GIZMO_INSTALL_CUSTOM, "custom_gizmo_path": "gizmos/nuke"})
            )

        custom_field = next(f for f in result.fields if f.name == "custom_gizmo_path")
        assert custom_field.default_value == "/home/user/workspace/gizmos/nuke"
