from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from griptape_nodes.node_library.workflow_registry import WorkflowRegistry
from griptape_nodes.retained_mode.events.flow_events import GetTopLevelFlowRequest, GetTopLevelFlowResultSuccess
from griptape_nodes.retained_mode.events.workflow_events import (
    PublishWorkflowResultFailure,
    PublishWorkflowResultSuccess,
    SaveWorkflowRequest,
    SaveWorkflowResultSuccess,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.retained_mode.publishing import WorkflowPackager

from publish_gizmo.nuke_discovery import GIZMO_INSTALL_CUSTOM
from publish_gizmo.nuke_gizmo_builder import NukeGizmoBuilder

if TYPE_CHECKING:
    from griptape_nodes.retained_mode.events.base_events import ResultPayload

logger = logging.getLogger(__name__)


class NukeGizmoPublisher:
    def __init__(self, workflow_name: str, metadata: dict | None = None) -> None:
        self._workflow_name = workflow_name
        self._metadata: dict = metadata or {}
        self._packager = WorkflowPackager(workflow_name)

    def publish_workflow(self) -> ResultPayload:
        try:
            self._packager.emit_progress(5.0, "Validating workflow...")
            errors = self._validate()
            if errors:
                return PublishWorkflowResultFailure(result_details="\n".join(str(e) for e in errors))

            self._packager.emit_progress(5.0, "Extracting workflow shape...")
            workflow_shape = GriptapeNodes.WorkflowManager().extract_workflow_shape(self._workflow_name)
            logger.info("Workflow shape: %s", workflow_shape)

            self._packager.emit_progress(5.0, "Saving workflow...")
            workflow = WorkflowRegistry.get_workflow_by_name(self._workflow_name)
            save_result = GriptapeNodes.handle_request(SaveWorkflowRequest(file_name=Path(workflow.file_path).stem))
            if not isinstance(save_result, SaveWorkflowResultSuccess):
                return PublishWorkflowResultFailure(result_details="Failed to save workflow before packaging.")

            self._packager.emit_progress(5.0, "Packaging workflow bundle...")
            install_dir = self._resolve_gizmo_install_path()
            if install_dir is None:
                msg = "Gizmo install path is not set."
                raise ValueError(msg)

            workflow_file_path = Path(WorkflowRegistry.get_complete_file_path(workflow.file_path))
            workflow_stem = workflow_file_path.stem

            # Single companion base dir per workflow; versions are subdirectories inside it
            companion_base = install_dir / "griptape_gizmos" / workflow_stem

            # Determine which version to write (new version or update current)
            version = self._determine_version(companion_base)
            version_dir = companion_base / f"v{version}"
            version_dir.mkdir(parents=True, exist_ok=True)

            # Package shared files (libraries, config, .env, pyproject.toml) into companion base.
            # The workflow file also lands here first — we move it into the version subdir below.
            self._packager.package_to_folder(companion_base, workflow)

            # Move the workflow file from companion base into the version subdir
            src_workflow = companion_base / workflow_file_path.name
            dest_workflow = version_dir / workflow_file_path.name
            if src_workflow.exists():
                shutil.move(str(src_workflow), str(dest_workflow))

            # Copy the runner and button scripts (shared, overwrite on each publish)
            self._packager.emit_progress(5.0, "Writing runner script...")
            runner_src = Path(__file__).parent / "nuke_workflow_runner.py"
            shutil.copy2(runner_src, companion_base / "run_workflow.py")
            run_button_src = Path(__file__).parent / "run_button.py"
            shutil.copy2(run_button_src, companion_base / "run_button.py")

            # Collect all version subdirectories for the gizmo version knob
            available_versions = self._collect_versions(companion_base)

            # Generate the wrapper gizmo with the stable name and version knob
            self._packager.emit_progress(10.0, "Generating gizmo...")
            builder = NukeGizmoBuilder(
                workflow_name=workflow_stem,
                workflow_shape=workflow_shape,
                companion_dir=str(companion_base),
                workflow_file=str(dest_workflow),
                available_versions=available_versions,
                current_version=version,
            )
            gizmo_text = builder.generate()

            wrapper_path = install_dir / f"{workflow_stem}.gizmo"
            wrapper_path.write_text(gizmo_text, encoding="utf-8")
            logger.info("Gizmo written to: %s", wrapper_path)

            # Persist the user's publish selections and version into the NukeStartFlow node metadata
            self._save_publish_config(wrapper_path, version)

            self._packager.emit_progress(10.0, "Gizmo installed successfully!")
            return PublishWorkflowResultSuccess(
                published_workflow_file_path=str(wrapper_path),
                skip_published_workflow_registration=True,
                result_details=f"Gizmo v{version} installed to: {wrapper_path}",
            )
        except Exception as e:
            logger.exception("Failed to publish workflow '%s'", self._workflow_name)
            return PublishWorkflowResultFailure(result_details=f"Failed to publish workflow: {e}")

    def _validate(self) -> list[Exception]:
        errors: list[Exception] = []
        start_flow = self._get_nuke_start_flow_node()
        if start_flow is None:
            errors.append(ValueError("No NukeStartFlow node found in the workflow."))
            return errors
        install_dir = self._resolve_gizmo_install_path()
        if install_dir is None:
            errors.append(ValueError("Gizmo install path is not configured. Please set it in the publish dialog."))
        return errors

    def _resolve_gizmo_install_path(self) -> Path | None:
        choice = self._metadata.get("gizmo_install_path")
        if choice == GIZMO_INSTALL_CUSTOM:
            choice = self._metadata.get("custom_gizmo_path")
        if not choice:
            return None
        return Path(choice)

    def _get_saved_version(self) -> int | None:
        """Read the saved version number from NukeStartFlow metadata, falling back to dialog metadata."""
        start_flow = self._get_nuke_start_flow_node()
        if start_flow is not None:
            saved = start_flow.metadata.get("publish_config", {})
            v = saved.get("version")
            if v is not None:
                return int(v)
        v = self._metadata.get("version")
        if v is not None:
            return int(v)
        return None

    def _collect_versions(self, companion_base: Path) -> list[int]:
        """Return a sorted list of version numbers from existing version subdirs."""
        versions = []
        if not companion_base.exists():
            return versions
        for p in companion_base.iterdir():
            if p.is_dir() and p.name.startswith("v"):
                try:
                    versions.append(int(p.name[1:]))
                except ValueError:
                    continue
        return sorted(versions)

    def _determine_version(self, companion_base: Path) -> int:
        """Determine the target version number based on update_mode metadata.

        - "update current version": keep the same version number (overwrite in place)
        - "publish new version": increment the version number
        - no saved version / first-time publish: scan disk, default to 1
        """
        update_mode = self._metadata.get("update_mode", "").lower()
        saved_version = self._get_saved_version()

        if "new version" in update_mode:
            return (saved_version or 0) + 1
        if "current version" in update_mode and saved_version is not None:
            return saved_version

        # First-time publish or fallback: scan disk for existing versions
        existing = self._collect_versions(companion_base)
        if existing:
            return max(existing) + 1
        return 1

    def _save_publish_config(self, gizmo_path: Path, version: int) -> None:
        """Persist publish selections and version into the NukeStartFlow node metadata for future pre-population."""
        start_flow = self._get_nuke_start_flow_node()
        if start_flow is None:
            return
        start_flow.metadata["publish_config"] = {
            "nuke": self._metadata.get("nuke"),
            "gizmo_install_path": self._metadata.get("gizmo_install_path"),
            "custom_gizmo_path": self._metadata.get("custom_gizmo_path"),
            "gizmo_path": str(gizmo_path),
            "version": version,
        }

    def _get_nuke_start_flow_node(self):  # noqa: ANN202
        result = GriptapeNodes.handle_request(GetTopLevelFlowRequest())
        if not isinstance(result, GetTopLevelFlowResultSuccess) or result.flow_name is None:
            return None
        control_flow = GriptapeNodes.FlowManager().get_flow_by_name(result.flow_name)
        for node in control_flow.nodes.values():
            if node.__class__.__name__ == "NukeStartFlow":
                return node
        return None
