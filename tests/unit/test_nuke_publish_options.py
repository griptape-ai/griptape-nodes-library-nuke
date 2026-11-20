"""Tests for the simplified Nuke publish dialog options (no Nuke-executable dropdown)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from griptape_nodes.retained_mode.events.workflow_events import GetPublishOptionsRequest

from publish_gizmo.nuke_discovery import GIZMO_INSTALL_CUSTOM, normalize_path_str
from publish_gizmo.nuke_publish_options import get_nuke_publish_options


def _request(current_selections: dict | None = None, configuration: dict | None = None) -> GetPublishOptionsRequest:
    return GetPublishOptionsRequest(
        workflow_name="my_workflow",
        publisher_name="nuke",
        current_selections=current_selections,
        configuration=configuration,
    )


class TestGetNukePublishOptions:
    def test_no_nuke_installation_field(self, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)
        result = get_nuke_publish_options(_request({}))
        names = [f.name for f in result.fields]
        assert "nuke" not in names

    def test_gizmo_install_path_field_has_no_dependency(self, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)
        result = get_nuke_publish_options(_request({}))
        gizmo_field = next(f for f in result.fields if f.name == "gizmo_install_path")
        assert gizmo_field.depends_on is None

    def test_default_choice_is_dot_nuke(self, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)
        result = get_nuke_publish_options(_request({}))
        gizmo_field = next(f for f in result.fields if f.name == "gizmo_install_path")
        assert gizmo_field.default_value == normalize_path_str(str(Path.home() / ".nuke"))
        assert gizmo_field.choices is not None
        assert gizmo_field.choices[0] == normalize_path_str(str(Path.home() / ".nuke"))
        assert gizmo_field.choices[-1] == GIZMO_INSTALL_CUSTOM

    def test_custom_gizmo_path_hidden_unless_custom_selected(self, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)
        result = get_nuke_publish_options(_request({"gizmo_install_path": GIZMO_INSTALL_CUSTOM}))
        custom_field = next(f for f in result.fields if f.name == "custom_gizmo_path")
        assert custom_field.hidden is False

        result = get_nuke_publish_options(_request({}))
        custom_field = next(f for f in result.fields if f.name == "custom_gizmo_path")
        assert custom_field.hidden is True

    def test_restores_from_remembered_configuration_with_stale_nuke_key(self, monkeypatch) -> None:
        """Old publish_config blobs saved before this simplification may still carry
        a 'nuke' key — restoring them must not error even though the field is gone."""
        monkeypatch.delenv("NUKE_PATH", raising=False)
        remembered = {
            "nuke": "/Applications/Nuke16.0v7",
            "gizmo_install_path": normalize_path_str(str(Path.home() / ".nuke")),
            "custom_gizmo_path": None,
            "gizmo_path": "/some/gizmo/path",
            "version": 2,
        }

        result = get_nuke_publish_options(_request(None, remembered))

        names = [f.name for f in result.fields]
        assert "nuke" not in names
        assert "update_mode" in names
        gizmo_field = next(f for f in result.fields if f.name == "gizmo_install_path")
        assert gizmo_field.default_value == normalize_path_str(str(Path.home() / ".nuke"))

    def test_saved_relative_custom_path_is_shown_absolute(self, monkeypatch) -> None:
        """Anchored to the workspace, since that is the base the file picker used."""
        monkeypatch.delenv("NUKE_PATH", raising=False)
        with patch("publish_gizmo.nuke_publish_options.GriptapeNodes") as griptape_nodes:
            griptape_nodes.ConfigManager.return_value.workspace_path = Path("/home/user/workspace")
            result = get_nuke_publish_options(
                _request({"gizmo_install_path": GIZMO_INSTALL_CUSTOM, "custom_gizmo_path": "gizmos/nuke"})
            )

        custom_field = next(f for f in result.fields if f.name == "custom_gizmo_path")
        assert custom_field.default_value == "/home/user/workspace/gizmos/nuke"


class TestDialogOpensOnTheRememberedPublish:
    def test_remembered_configuration_offers_to_update_its_version(self, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)
        configuration = {
            "gizmo_install_path": None,
            "custom_gizmo_path": None,
            "gizmo_path": "/opt/wf_v3.gizmo",
            "version": 3,
        }

        result = get_nuke_publish_options(_request(None, configuration))

        update_mode = next(f for f in result.fields if f.name == "update_mode")
        assert update_mode.default_value == "Update current version (v3)"
        assert result.button_label == "Update"

    def test_no_remembered_configuration_means_a_first_publish(self, monkeypatch) -> None:
        monkeypatch.delenv("NUKE_PATH", raising=False)

        result = get_nuke_publish_options(_request(None, None))

        assert "update_mode" not in [f.name for f in result.fields]
