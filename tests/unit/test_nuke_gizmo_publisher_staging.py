"""Tests that a re-publish rebuilds the companion bundle rather than merging into it."""

from __future__ import annotations

from contextlib import contextmanager
from fnmatch import fnmatch
from pathlib import Path
from unittest import mock

import pytest
from griptape_nodes.retained_mode.events.os_events import WriteFileRequest, WriteFileResultSuccess
from griptape_nodes.retained_mode.events.workflow_events import SaveWorkflowRequest, SaveWorkflowResultSuccess

from publish_gizmo.constants import PRESERVED_ON_REPUBLISH, VERSION_DIR_GLOB
from publish_gizmo.nuke_gizmo_publisher import NukeGizmoPublisher


class TestPreservedEntries:
    def test_version_dirs_are_preserved(self) -> None:
        """Version subdirs accumulate by design -- a rebuild must not delete v1..vN."""
        assert VERSION_DIR_GLOB in PRESERVED_ON_REPUBLISH

    def test_version_pattern_matches_version_dirs_only(self) -> None:
        assert fnmatch("v1", VERSION_DIR_GLOB)
        assert fnmatch("v12", VERSION_DIR_GLOB)
        # A bundle artifact that merely starts with "v" must still be rebuilt.
        assert not fnmatch("version.txt", VERSION_DIR_GLOB)
        assert not fnmatch("vendor", VERSION_DIR_GLOB)

    def test_run_output_dirs_are_preserved(self) -> None:
        """A gizmo run driven from an unsaved .nk writes its outputs into the bundle.

        Deleting an artist's generated frames on re-publish would be worse than the
        staleness the rebuild fixes.
        """
        assert "griptape_outputs" in PRESERVED_ON_REPUBLISH
        assert "staticfiles" in PRESERVED_ON_REPUBLISH


def _handle_request(request):  # noqa: ANN001, ANN202
    if isinstance(request, SaveWorkflowRequest):
        return SaveWorkflowResultSuccess(result_details="saved", file_path="wf.py", workflow_name="wf")
    if isinstance(request, WriteFileRequest):
        return WriteFileResultSuccess(result_details="written", final_file_path=str(request.file_path), bytes_written=1)
    msg = f"unexpected request: {type(request).__name__}"
    raise AssertionError(msg)


@contextmanager
def _publish(publisher: NukeGizmoPublisher, install_dir: Path, staging: Path):  # noqa: ANN201
    """Drive publish_workflow with everything outside the staging swap stubbed out."""
    with (
        mock.patch.object(publisher, "_validate", return_value=[]),
        mock.patch.object(publisher, "_resolve_gizmo_install_path", return_value=install_dir),
        mock.patch.object(publisher, "_determine_version", return_value=2),
        mock.patch.object(publisher, "_build_bundle", return_value=(staging / "v2" / "wf.py", None)) as build_bundle,
        mock.patch.object(publisher, "_collect_versions", return_value=[1, 2]),
        mock.patch.object(publisher, "_ensure_init_plugin_path"),
        mock.patch.object(publisher, "_regenerate_menu_py"),
        mock.patch.object(publisher, "_save_publish_config"),
        mock.patch("publish_gizmo.nuke_gizmo_publisher.WorkflowRegistry") as registry,
        mock.patch("publish_gizmo.nuke_gizmo_publisher.GriptapeNodes") as griptape_nodes,
        mock.patch("publish_gizmo.nuke_gizmo_publisher.NukeGizmoBuilder") as builder,
    ):
        registry.get_workflow_by_name.return_value = mock.Mock(file_path="wf.py")
        registry.get_complete_file_path.return_value = str(install_dir.parent / "wf.py")
        griptape_nodes.handle_request.side_effect = _handle_request
        yield build_bundle, builder


@pytest.fixture
def publisher():  # noqa: ANN201
    with mock.patch("publish_gizmo.nuke_gizmo_publisher.WorkflowPackager"):
        return NukeGizmoPublisher(workflow_name="wf")


@pytest.fixture
def staging(tmp_path, publisher):  # noqa: ANN001, ANN201
    path = tmp_path / "wf.staging"
    path.mkdir()
    publisher._packager.staged_publish.return_value.__enter__.return_value = path  # noqa: SLF001
    return path


class TestBundleIsStaged:
    def test_bundle_is_built_in_staging_not_in_the_live_companion(self, publisher, tmp_path, staging) -> None:
        """A publish that fails partway must leave the previous bundle untouched."""
        install_dir = tmp_path / "nuke"
        with _publish(publisher, install_dir, staging) as (build_bundle, _):
            result = publisher.publish_workflow()

        assert not isinstance(result, type(None))
        assert build_bundle.call_args[0][0] == staging

    def test_accumulated_entries_are_carried_across_the_rebuild(self, publisher, tmp_path, staging) -> None:
        with _publish(publisher, tmp_path / "nuke", staging):
            publisher.publish_workflow()

        staged_publish = publisher._packager.staged_publish  # noqa: SLF001
        assert staged_publish.call_args.kwargs["preserve"] == PRESERVED_ON_REPUBLISH

    def test_swap_targets_the_companion_directory(self, publisher, tmp_path, staging) -> None:
        install_dir = tmp_path / "nuke"
        with _publish(publisher, install_dir, staging):
            publisher.publish_workflow()

        staged_publish = publisher._packager.staged_publish  # noqa: SLF001
        assert staged_publish.call_args[0][0] == install_dir / "griptape" / "wf"

    def test_gizmo_records_the_final_path_not_the_staging_path(self, publisher, tmp_path, staging) -> None:
        """The gizmo resolves its workflow at run time, so a staging path would dangle."""
        install_dir = tmp_path / "nuke"
        with _publish(publisher, install_dir, staging) as (_, builder):
            publisher.publish_workflow()

        workflow_file = Path(builder.call_args.kwargs["workflow_file"])
        assert workflow_file == install_dir / "griptape" / "wf" / "v2" / "wf.py"
        assert staging not in workflow_file.parents

    def test_unpinned_deps_are_reported_in_the_publish_result(self, publisher, tmp_path, staging) -> None:
        """Locking is best-effort, so the artist has to hear about it from the publish
        result — the log alone is not somewhere they look."""
        with _publish(publisher, tmp_path / "nuke", staging) as (build_bundle, _):
            build_bundle.return_value = (staging / "v2" / "wf.py", "uv not found on PATH")
            result = publisher.publish_workflow()

        assert "uv not found on PATH" in str(result.result_details)

    def test_pinned_deps_add_no_warning_to_the_publish_result(self, publisher, tmp_path, staging) -> None:
        with _publish(publisher, tmp_path / "nuke", staging):
            result = publisher.publish_workflow()

        assert "Warning" not in str(result.result_details)
