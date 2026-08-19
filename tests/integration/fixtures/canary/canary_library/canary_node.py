"""Fixture node for the workspace-not-moved integration tests.

Declares an unconditional static-file dependency and writes a project-relative
output file, so a published bundle exercises both static-file resolution against
``workspace_path`` and ``{outputs}`` macro resolution.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from griptape.artifacts import ImageUrlArtifact
from griptape_nodes.common.macro_parser import ParsedMacro
from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode, NodeDependencies
from griptape_nodes.exe_types.param_components.project_file_parameter import ProjectFileParameter
from griptape_nodes.files.file import File
from griptape_nodes.files.project_file import ProjectFileDestination
from griptape_nodes.retained_mode.events.project_events import GetPathForMacroRequest, GetPathForMacroResultSuccess
from griptape_nodes.retained_mode.events.static_file_events import (
    CreateStaticFileRequest,
    CreateStaticFileResultSuccess,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

CANARY_STATIC_FILE = "assets/canary_asset.txt"
CANARY_MACRO_STATIC_FILE = "{inputs}/canary_macro_asset.txt"
CANARY_SITUATION_FILE = "canary_file.txt"

# Written for real through StaticFilesManager, which takes its directory from config rather than
# from the project template, so no situation override can move it.
CANARY_CREATED_STATIC_FILE = "canary_created_static.txt"

# Project directory macros surfaced as extra outputs so the integration tests can see where a
# published bundle's writable directories actually resolve. Parameter name -> macro text: the
# engine's own directory names carry hyphens, which are legal inside a macro but make for an
# awkward Nuke port name, so the two are kept apart.
CANARY_DIRECTORY_MACROS = {
    "temp_dir": "{temp}",
    "backups_dir": "{backups}",
    "workflow_run_failures_dir": "{workflow_run_failures}",
    "previews_dir": "{griptape-nodes-previews}",
    "metadata_dir": "{griptape-nodes-metadata}",
    "thumbnails_dir": "{griptape-nodes-thumbnails}",
}


class CanaryNode(DataNode):
    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata=metadata)
        self.add_parameter(
            Parameter(
                name="static_file_path",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="macro_static_file_path",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="output_path",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="image_url_artifact",
                tooltip="",
                type="ImageUrlArtifact",
                default_value=None,
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="project_dir",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="workflow_dir",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="workspace_dir",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="env_sentinel",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        for parameter_name in CANARY_DIRECTORY_MACROS:
            self.add_parameter(
                Parameter(
                    name=parameter_name,
                    tooltip="",
                    type="str",
                    default_value="",
                    allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
                )
            )
        self.add_parameter(
            Parameter(
                name="situation_save_file",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_copy_external_file",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_download_url",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_save_node_output",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_save_griptape_nodes_preview",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_save_static_file",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_save_griptape_nodes_metadata",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_save_workflow",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_create_versioned_workflow",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_save_workflow_thumbnail",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_save_failed_workflow",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_save_temp_file",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="situation_save_workflow_backup",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="created_static_file_url",
                tooltip="",
                type="str",
                default_value="",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
            )
        )
        self._file_param = ProjectFileParameter(node=self, name="output_file", default_filename="canary_output.txt")
        self._file_param.add_parameter()

    def get_node_dependencies(self) -> NodeDependencies | None:
        deps = super().get_node_dependencies()
        if deps is None:
            deps = NodeDependencies()
        deps.static_files.update({CANARY_STATIC_FILE, CANARY_MACRO_STATIC_FILE})
        return deps

    def process(self) -> None:
        # Attempt to read relative path static file dependency.
        static_file_path = File(CANARY_STATIC_FILE).resolve()
        if not Path(static_file_path).is_file():
            msg = f"Attempted to read static asset for {self.name}. Failed because '{static_file_path}' does not exist."
            raise ValueError(msg)
        self.parameter_output_values["static_file_path"] = str(static_file_path)

        # Attempt to read macro path static file dependency.
        parsed_macro = ParsedMacro(CANARY_MACRO_STATIC_FILE)
        result = GriptapeNodes.handle_request(GetPathForMacroRequest(parsed_macro=parsed_macro, variables={}))
        if not isinstance(result, GetPathForMacroResultSuccess):
            raise ValueError(f"{{inputs}} macro did not resolve: {result.result_details}")
        resolved = result.absolute_path
        if not resolved.is_file():
            raise ValueError(f"{{inputs}} macro did not resolve to a file: {resolved}")
        self.parameter_output_values["macro_static_file_path"] = str(resolved)

        # Write output file at provided output path.
        written_file = self._file_param.build_file().write_text("canary payload\n")
        written_name = Path(written_file.resolve()).name
        macro_path = f"{{outputs}}/{written_name}"
        self.parameter_output_values["output_path"] = macro_path
        # The ecosystem's own pattern: SaveImage hands back the portable macro form
        # wrapped in an artifact, which the engine's output-parameter macro substitution
        # does not look inside, by default.
        self.parameter_output_values["image_url_artifact"] = ImageUrlArtifact(value=macro_path)

        # Passthrough macros for assertion in test.
        self.parameter_output_values["project_dir"] = "{project_dir}"
        self.parameter_output_values["workflow_dir"] = "{workflow_dir}"
        self.parameter_output_values["workspace_dir"] = "{workspace_dir}"
        self.parameter_output_values["env_sentinel"] = "{GTN_NUKE_CANARY_SENTINEL}"
        for parameter_name, macro in CANARY_DIRECTORY_MACROS.items():
            self.parameter_output_values[parameter_name] = macro

        # Where each built-in situation would put a file, so the tests can see which of them a
        # published bundle sends back into the installed gizmo.
        self.parameter_output_values["situation_save_file"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="save_file"
        ).resolve()
        self.parameter_output_values["situation_copy_external_file"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="copy_external_file"
        ).resolve()
        self.parameter_output_values["situation_download_url"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="download_url", sanitized_url=CANARY_SITUATION_FILE
        ).resolve()
        self.parameter_output_values["situation_save_node_output"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="save_node_output", _index=1
        ).resolve()
        self.parameter_output_values["situation_save_griptape_nodes_preview"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE,
            situation="save_griptape_nodes_preview",
            source_file_name=CANARY_SITUATION_FILE,
            preview_format="png",
        ).resolve()
        self.parameter_output_values["situation_save_static_file"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="save_static_file"
        ).resolve()
        self.parameter_output_values["situation_save_griptape_nodes_metadata"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="save_griptape_nodes_metadata", source_file_name=CANARY_SITUATION_FILE
        ).resolve()
        self.parameter_output_values["situation_save_workflow"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="save_workflow"
        ).resolve()
        self.parameter_output_values["situation_create_versioned_workflow"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="create_versioned_workflow"
        ).resolve()
        self.parameter_output_values["situation_save_workflow_thumbnail"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="save_workflow_thumbnail"
        ).resolve()
        self.parameter_output_values["situation_save_failed_workflow"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="save_failed_workflow", _index=1
        ).resolve()
        self.parameter_output_values["situation_save_temp_file"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="save_temp_file"
        ).resolve()
        self.parameter_output_values["situation_save_workflow_backup"] = ProjectFileDestination.from_situation(
            CANARY_SITUATION_FILE, situation="save_workflow_backup", _index=1
        ).resolve()

        # Actually write one, rather than only resolving where it would go: the resolved path and
        # the written one come from different code paths in StaticFilesManager.
        create_result = GriptapeNodes.handle_request(
            CreateStaticFileRequest(
                content=base64.b64encode(b"canary static payload\n").decode("utf-8"),
                file_name=CANARY_CREATED_STATIC_FILE,
            )
        )
        if not isinstance(create_result, CreateStaticFileResultSuccess):
            msg = f"Attempted to create static file '{CANARY_CREATED_STATIC_FILE}'. Failed because {create_result.result_details}."
            raise ValueError(msg)
        self.parameter_output_values["created_static_file_url"] = create_result.url
