"""Builds and publishes the canary workflow gizmo used by the integration tests.

Shared by ``conftest.py``'s ``published_bundle`` fixture and
``publish_canary_gizmo.py`` (the one-time ``.nk`` fixture generator for the
real-Nuke wiring check), so both drive the exact same workflow-construction path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from griptape_nodes.retained_mode.events.connection_events import CreateConnectionRequest, CreateConnectionResultSuccess
from griptape_nodes.retained_mode.events.context_events import SetWorkflowContextRequest, SetWorkflowContextSuccess
from griptape_nodes.retained_mode.events.flow_events import CreateFlowRequest, CreateFlowResultSuccess
from griptape_nodes.retained_mode.events.library_events import (
    RegisterLibraryFromFileRequest,
    RegisterLibraryFromFileResultSuccess,
)
from griptape_nodes.retained_mode.events.node_events import CreateNodeRequest, CreateNodeResultSuccess
from griptape_nodes.retained_mode.events.parameter_events import AddParameterToNodeRequest
from griptape_nodes.retained_mode.events.project_events import (
    ActivateWorkspaceProjectRequest,
    ActivateWorkspaceProjectResultSuccess,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    PublishWorkflowResultSuccess,
    SaveWorkflowRequest,
    SaveWorkflowResultSuccess,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.utils.version_utils import engine_version

from publish_gizmo.constants import versioned_node_name
from publish_gizmo.nuke_discovery import GIZMO_INSTALL_CUSTOM
from publish_gizmo.nuke_gizmo_publisher import NukeGizmoPublisher

if TYPE_CHECKING:
    from collections.abc import Callable

CANARY_LIBRARY_DIR = Path(__file__).parent / "canary_library"
NUKE_LIBRARY_DIR = Path(__file__).parents[4]

WORKFLOW_NAME = "canary_workflow"
GIZMO_NODE_NAME = versioned_node_name(WORKFLOW_NAME, 1)

# Macro-bearing CanaryNode outputs the tests assert on, each surfaced through Nuke End Flow. The
# env_sentinel names nothing the engine computes, and is here to pin that such a name is handed back
# byte-identical rather than resolved from the bundled .env.
_MACRO_OUTPUTS = [
    "project_dir",
    "workflow_dir",
    "workspace_dir",
    "env_sentinel",
    "temp_dir",
    "backups_dir",
    "workflow_run_failures_dir",
    "previews_dir",
    "metadata_dir",
    "thumbnails_dir",
    "static_file_path",
    "macro_static_file_path",
    "situation_save_file",
    "situation_copy_external_file",
    "situation_download_url",
    "situation_save_node_output",
    "situation_save_griptape_nodes_preview",
    "situation_save_static_file",
    "situation_save_griptape_nodes_metadata",
    "situation_save_workflow",
    "situation_create_versioned_workflow",
    "situation_save_workflow_thumbnail",
    "situation_save_failed_workflow",
    "situation_save_temp_file",
    "situation_save_workflow_backup",
    "created_static_file_url",
]


@dataclass(frozen=True)
class PublishedBundle:
    """Paths into a gizmo bundle produced by ``publish_canary_bundle``."""

    workspace: Path
    install_dir: Path
    griptape_dir: Path
    companion_base: Path
    version_dir: Path
    workflow_file: Path
    gizmo_path: Path


def publish_canary_bundle(
    *,
    workspace: Path,
    install_dir: Path,
    project_id: str | None = None,
    set_env_var: Callable[[str, str], None] = os.environ.__setitem__,
) -> PublishedBundle:
    """Register canary_library, build Start -> Canary -> End, save, and publish the gizmo.

    Args:
        workspace: Directory to use as ``workspace_path``. The static asset
            ``CanaryNode`` depends on is created here before publishing so the
            packager bundles it.
        install_dir: Gizmo install directory passed to ``NukeGizmoPublisher``.
        project_id: If given, a workspace ``griptape-nodes-project.yml`` declaring this
            id is written and activated before publishing, so the bundled project.yml
            carries an explicit id instead of the path-derived fallback. That matches a
            real bundle: ``ProjectTemplate.id`` is a GUID the UI sets on every project it
            creates. Left None, publishing happens against system defaults, which declare
            no id at all.
        set_env_var: How the GTN_CONFIG_ overrides this function needs are exported.
            The default raw write suits the standalone ``publish_canary_gizmo`` script,
            which owns its whole process; a pytest caller must pass
            ``monkeypatch.setenv`` so the values do not survive into later tests.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "assets").mkdir(exist_ok=True)
    (workspace / "assets" / "canary_asset.txt").write_text("canary asset\n")

    # To be resolved through `{inputs}` macro.
    (workspace / "inputs").mkdir(exist_ok=True)
    (workspace / "inputs" / "canary_macro_asset.txt").write_text("canary input\n")

    set_env_var("GTN_CONFIG_WORKSPACE_DIRECTORY", str(workspace))
    set_env_var("GTN_CONFIG_ENABLE_WORKSPACE_FILE_WATCHING", "false")

    if project_id is not None:
        workspace_project_yml = workspace / "griptape-nodes-project.yml"
        workspace_project_yml.write_text(
            f'project_template_schema_version: "1.0.0"\nid: "{project_id}"\nname: "Canary Project"\n'
            "situations: {}\ndirectories: {}\n"
        )
        activate_result = GriptapeNodes.handle_request(ActivateWorkspaceProjectRequest())
        assert isinstance(activate_result, ActivateWorkspaceProjectResultSuccess), activate_result

    library_json = NUKE_LIBRARY_DIR / "griptape-nodes-library.json"
    register_result = GriptapeNodes.handle_request(RegisterLibraryFromFileRequest(file_path=str(library_json)))
    assert isinstance(register_result, RegisterLibraryFromFileResultSuccess), register_result

    library_json = _materialize_canary_library(workspace.parent / "canary_library")
    register_result = GriptapeNodes.handle_request(RegisterLibraryFromFileRequest(file_path=str(library_json)))
    assert isinstance(register_result, RegisterLibraryFromFileResultSuccess), register_result

    # Simulate new unsaved workflow.
    context_result = GriptapeNodes.handle_request(SetWorkflowContextRequest())
    assert isinstance(context_result, SetWorkflowContextSuccess), context_result

    flow_result = GriptapeNodes.handle_request(
        CreateFlowRequest(parent_flow_name=None, flow_name="ControlFlow_1", set_as_new_context=False)
    )
    assert isinstance(flow_result, CreateFlowResultSuccess), flow_result

    _create_node("NukeStartFlow", "Nuke Start Flow", flow_result.flow_name)
    _create_node("CanaryNode", "Canary", flow_result.flow_name)
    _create_node("NukeEndFlow", "Nuke End Flow", flow_result.flow_name)

    _connect("Nuke Start Flow", "exec_out", "Canary", "exec_in")
    _connect("Canary", "exec_out", "Nuke End Flow", "exec_in")

    # NukeEndFlow only exposes its own default outputs (was_successful, result_details);
    # a custom output must be added explicitly for extract_workflow_shape() to surface it.
    add_param_result = GriptapeNodes.handle_request(
        AddParameterToNodeRequest(
            node_name="Nuke End Flow",
            parameter_name="output_path",
            default_value="",
            tooltip="Canary output",
            type="str",
            input_types=["str"],
            mode_allowed_output=False,
        )
    )
    assert add_param_result.succeeded(), add_param_result
    _connect("Canary", "output_path", "Nuke End Flow", "output_path")

    # The same output path again, but carried inside an artifact rather than as a bare string.
    add_artifact_param_result = GriptapeNodes.handle_request(
        AddParameterToNodeRequest(
            node_name="Nuke End Flow",
            parameter_name="image_url_artifact",
            default_value=None,
            tooltip="Canary artifact output",
            type="ImageUrlArtifact",
            input_types=["ImageUrlArtifact"],
            mode_allowed_output=False,
        )
    )
    assert add_artifact_param_result.succeeded(), add_artifact_param_result
    _connect("Canary", "image_url_artifact", "Nuke End Flow", "image_url_artifact")

    for macro_name in _MACRO_OUTPUTS:
        add_macro_param_result = GriptapeNodes.handle_request(
            AddParameterToNodeRequest(
                node_name="Nuke End Flow",
                parameter_name=macro_name,
                default_value="",
                type="str",
                tooltip="",
                input_types=["str"],
                mode_allowed_output=False,
            )
        )
        assert add_macro_param_result.succeeded(), add_macro_param_result
        _connect("Canary", macro_name, "Nuke End Flow", macro_name)

    # Saving rekeys the unsaved entry to a path-derived registry key, so that -- not WORKFLOW_NAME
    # -- is what the publisher must be handed.
    save_result = GriptapeNodes.handle_request(SaveWorkflowRequest(file_name=WORKFLOW_NAME))
    assert isinstance(save_result, SaveWorkflowResultSuccess), save_result

    install_dir.mkdir(parents=True, exist_ok=True)
    publisher = NukeGizmoPublisher(
        workflow_name=save_result.workflow_name,  # == Registry key
        metadata={"gizmo_install_path": GIZMO_INSTALL_CUSTOM, "custom_gizmo_path": str(install_dir)},
    )
    publish_result = publisher.publish_workflow()
    assert isinstance(publish_result, PublishWorkflowResultSuccess), publish_result

    griptape_dir = install_dir / "griptape"
    companion_base = griptape_dir / WORKFLOW_NAME
    version_dir = companion_base / "v1"
    return PublishedBundle(
        workspace=workspace,
        install_dir=install_dir,
        griptape_dir=griptape_dir,
        companion_base=companion_base,
        version_dir=version_dir,
        workflow_file=version_dir / f"{WORKFLOW_NAME}.py",
        gizmo_path=Path(publish_result.published_workflow_file_path),
    )


def _materialize_canary_library(target_dir: Path) -> Path:
    """Copy fixtures/canary/canary_library into a tmp dir, pinned to the running engine version."""
    target_dir.mkdir(parents=True, exist_ok=True)
    schema = json.loads((CANARY_LIBRARY_DIR / "griptape_nodes_library.json").read_text())
    schema["metadata"]["engine_version"] = engine_version
    (target_dir / "griptape_nodes_library.json").write_text(json.dumps(schema, indent=2))
    for node_entry in schema["nodes"]:
        source = CANARY_LIBRARY_DIR / node_entry["file_path"]
        (target_dir / node_entry["file_path"]).write_text(source.read_text())
    return target_dir / "griptape_nodes_library.json"


def _create_node(node_type: str, node_name: str, flow_name: str) -> None:
    result = GriptapeNodes.handle_request(
        CreateNodeRequest(
            node_type=node_type,
            node_name=node_name,
            override_parent_flow_name=flow_name,
        )
    )
    assert isinstance(result, CreateNodeResultSuccess), result


def _connect(source_node: str, source_param: str, target_node: str, target_param: str) -> None:
    result = GriptapeNodes.handle_request(
        CreateConnectionRequest(
            source_node_name=source_node,
            source_parameter_name=source_param,
            target_node_name=target_node,
            target_parameter_name=target_param,
        )
    )
    assert isinstance(result, CreateConnectionResultSuccess), result
