"""Tests that the gizmo install path is absolute by the time the publish uses it.

A relative install dir cannot survive the publish: one value gets resolved against
different bases depending on which layer touches it -- the engine's event layer anchors
to the workspace, the publisher's plain ``pathlib`` calls to the engine's working
directory -- so the publisher anchors it once itself.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from publish_gizmo.nuke_discovery import GIZMO_INSTALL_CUSTOM
from publish_gizmo.nuke_gizmo_publisher import NukeGizmoPublisher

WORKSPACE = "/home/user/workspace"


def _publisher(metadata: dict) -> NukeGizmoPublisher:
    with mock.patch("publish_gizmo.nuke_gizmo_publisher.WorkflowPackager"):
        return NukeGizmoPublisher(workflow_name="wf", metadata=metadata)


def _resolve(metadata: dict, workspace: str = WORKSPACE) -> Path | None:
    publisher = _publisher(metadata)
    with mock.patch("publish_gizmo.nuke_gizmo_publisher.GriptapeNodes") as griptape_nodes:
        griptape_nodes.ConfigManager.return_value.workspace_path = Path(workspace)
        return publisher._resolve_gizmo_install_path()  # noqa: SLF001


def _custom(path: str) -> dict:
    return {"gizmo_install_path": GIZMO_INSTALL_CUSTOM, "custom_gizmo_path": path}


class TestResolveGizmoInstallPath:
    def test_relative_custom_path_is_anchored_to_the_workspace(self) -> None:
        assert _resolve(_custom("gizmos/nuke")) == Path(f"{WORKSPACE}/gizmos/nuke")

    def test_absolute_custom_path_is_unchanged(self) -> None:
        assert _resolve(_custom("/opt/studio/gizmos")) == Path("/opt/studio/gizmos")

    def test_tilde_is_expanded(self) -> None:
        assert _resolve(_custom("~/.nuke")) == Path.home() / ".nuke"

    def test_dropdown_selection_is_also_absolutized(self) -> None:
        assert _resolve({"gizmo_install_path": "dotnuke"}) == Path(f"{WORKSPACE}/dotnuke")

    def test_missing_path_returns_none(self) -> None:
        assert _resolve({"gizmo_install_path": GIZMO_INSTALL_CUSTOM, "custom_gizmo_path": ""}) is None
        assert _resolve({}) is None

    def test_redundant_separators_are_normalized(self) -> None:
        assert _resolve(_custom("/opt//studio/./gizmos")) == Path("/opt/studio/gizmos")

    def test_share_path_is_not_symlink_resolved(self, tmp_path) -> None:
        """A studio share is routinely reached through a symlink whose target differs per host.

        Resolving it would put a host-specific path into pluginAddPath and the
        reported gizmo path.
        """
        target = tmp_path / "net" / "fileserver" / "studio"
        target.mkdir(parents=True)
        link = tmp_path / "mnt_studio"
        link.symlink_to(target)

        assert _resolve(_custom(str(link))) == link

    @pytest.mark.skipif(os.name != "nt", reason="drive-letter paths are only absolute on Windows")
    def test_windows_share_path_is_unchanged(self) -> None:
        assert str(_resolve(_custom("Z:/gizmos"))) == "Z:/gizmos"


class TestValidateInstallPath:
    def _validate(self, metadata: dict) -> list[Exception]:
        publisher = _publisher(metadata)
        with (
            mock.patch.object(publisher, "_get_nuke_start_flow_node", return_value=mock.Mock()),
            mock.patch("publish_gizmo.nuke_gizmo_publisher.GriptapeNodes") as griptape_nodes,
        ):
            griptape_nodes.ConfigManager.return_value.workspace_path = Path(WORKSPACE)
            return publisher._validate()  # noqa: SLF001

    def test_missing_directory_passes_because_the_publish_creates_it(self) -> None:
        """First-time config of a machine has no ~/.nuke yet, and that has to publish."""
        assert self._validate(_custom("gizmos/nuke")) == []

    def test_unconfigured_path_is_reported(self) -> None:
        errors = self._validate({})
        assert len(errors) == 1
        assert "not configured" in str(errors[0])

    def test_existing_directory_passes(self, tmp_path) -> None:
        assert self._validate(_custom(str(tmp_path))) == []

    def test_file_instead_of_directory_is_rejected(self, tmp_path) -> None:
        """Named with the resolved path, so an accidentally workspace-relative pick is visible."""
        target = tmp_path / "not_a_dir"
        target.write_text("")
        errors = self._validate(_custom(str(target)))
        assert len(errors) == 1
        assert str(target) in str(errors[0])


class TestSavePublishConfig:
    def test_resolved_custom_path_is_stored(self) -> None:
        """The dialog re-reads this value, so storing the relative one reintroduces the bug."""
        publisher = _publisher(_custom("gizmos/nuke"))
        start_flow = mock.Mock()
        start_flow.metadata = {}
        with (
            mock.patch.object(publisher, "_get_nuke_start_flow_node", return_value=start_flow),
            mock.patch("publish_gizmo.nuke_gizmo_publisher.GriptapeNodes") as griptape_nodes,
        ):
            griptape_nodes.ConfigManager.return_value.workspace_path = Path(WORKSPACE)
            publisher._save_publish_config(Path("/opt/studio/gizmos/wf_v1.gizmo"), 1)  # noqa: SLF001

        assert start_flow.metadata["publish_config"]["custom_gizmo_path"] == f"{WORKSPACE}/gizmos/nuke"
