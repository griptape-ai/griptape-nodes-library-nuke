from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from griptape_nodes.common.project_templates import load_project_template_from_yaml
from griptape_nodes.common.project_templates.directory import DirectoryDefinition
from griptape_nodes.common.project_templates.validation import ProjectValidationInfo, ProjectValidationStatus
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

            # Package everything into the companion directory
            self._packager.emit_progress(5.0, "Packaging workflow bundle...")
            install_dir = self._resolve_gizmo_install_path()
            if install_dir is None:
                msg = "Gizmo install path is not set."
                raise ValueError(msg)

            workflow_file_path = Path(WorkflowRegistry.get_complete_file_path(workflow.file_path))
            workflow_stem = workflow_file_path.stem
            companion_dir = install_dir / "griptape_gizmos" / workflow_stem

            # Use WorkflowPackager for the full standard bundle
            # (workflow file, libraries, config, .env, static files, pyproject.toml)
            self._packager.package_to_folder(companion_dir, workflow)

            # Overwrite project.yml with absolute paths so outputs save in the gizmo folder
            self._write_nuke_project_template(companion_dir)

            # Copy the runner script into companion directory
            self._packager.emit_progress(5.0, "Writing runner script...")
            runner_src = Path(__file__).parent / "nuke_workflow_runner.py"
            runner_dest = companion_dir / "run_workflow.py"
            shutil.copy2(runner_src, runner_dest)

            # Generate the .gizmo file
            self._packager.emit_progress(10.0, "Generating gizmo...")
            dest_workflow = companion_dir / workflow_file_path.name
            builder = NukeGizmoBuilder(
                workflow_name=workflow_stem,
                workflow_shape=workflow_shape,
                companion_dir=str(companion_dir),
                workflow_file=str(dest_workflow),
            )
            gizmo_text = builder.generate()

            gizmo_path = install_dir / f"{workflow_stem}.gizmo"
            gizmo_path.write_text(gizmo_text, encoding="utf-8")
            logger.info("Gizmo written to: %s", gizmo_path)

            # Persist the user's publish selections into the NukeStartFlow node metadata
            # so the next publish dialog is pre-populated.
            self._save_publish_config()

            self._packager.emit_progress(10.0, "Gizmo installed successfully!")
            return PublishWorkflowResultSuccess(
                published_workflow_file_path=str(gizmo_path),
                skip_published_workflow_registration=True,
                result_details=f"Gizmo installed to: {gizmo_path}",
            )
        except Exception as e:
            logger.exception("Failed to publish workflow '%s'", self._workflow_name)
            return PublishWorkflowResultFailure(result_details=f"Failed to publish workflow: {e}")

    def _write_nuke_project_template(self, companion_dir: Path) -> None:
        """Overwrite project.yml with absolute paths so outputs save in the gizmo folder.

        The packager writes relative path_macros (e.g. "outputs"). Nuke runs the workflow
        in a subprocess with GTN_CONFIG_WORKSPACE_DIRECTORY set to companion_dir, so
        ProjectFileDestination converts written paths back to macro form (e.g.
        "{outputs}/file.jpg") when storing output values. Absolute path_macros ensure the
        gizmo receives real absolute paths.
        """
        project_yml = companion_dir / "project.yml"
        if not project_yml.exists():
            return

        validation_info = ProjectValidationInfo(status=ProjectValidationStatus.GOOD)
        template = load_project_template_from_yaml(project_yml.read_text(encoding="utf-8"), validation_info)
        if template is None:
            logger.warning("Could not parse project.yml for Nuke path rewrite. Skipping.")
            return

        # Point outputs and inputs directly at the companion directory so all
        # generated files land in the gizmo folder alongside the workflow.
        absolute_path_overrides = {
            "outputs": str(companion_dir),
            "inputs": str(companion_dir),
            "temp": str(companion_dir / "temp"),
        }
        for dir_name, override_path in absolute_path_overrides.items():
            if dir_name in template.directories:
                template.directories[dir_name] = DirectoryDefinition(
                    name=dir_name,
                    path_macro=override_path,
                )

        project_yml.write_text(template.to_yaml(include_comments=False), encoding="utf-8")

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

    def _save_publish_config(self) -> None:
        """Persist publish selections into the NukeStartFlow node metadata for future pre-population."""
        start_flow = self._get_nuke_start_flow_node()
        if start_flow is None:
            return
        start_flow.metadata["publish_config"] = {
            "nuke": self._metadata.get("nuke"),
            "gizmo_install_path": self._metadata.get("gizmo_install_path"),
            "custom_gizmo_path": self._metadata.get("custom_gizmo_path"),
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
