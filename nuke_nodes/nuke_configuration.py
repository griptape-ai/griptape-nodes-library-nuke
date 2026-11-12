"""Nuke Configuration node, which the engine adds after the first publish to remember its settings."""

from __future__ import annotations

from typing import Any

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import ConfigurationNode

from publish_gizmo.publish_config import CUSTOM_GIZMO_PATH, GIZMO_INSTALL_PATH, GIZMO_PATH, VERSION


class NukeConfiguration(ConfigurationNode):
    """Where the gizmo is installed and which file and version the last publish wrote."""

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)
        for parameter_name, parameter_type, display_name, tooltip in (
            (GIZMO_INSTALL_PATH, "str", "Gizmo Install Path", "Plugin directory the gizmo is installed into."),
            (CUSTOM_GIZMO_PATH, "str", "Custom Gizmo Path", "Directory used when the install path is custom."),
            (GIZMO_PATH, "str", "Gizmo Path", "The gizmo file the last publish wrote."),
            (VERSION, "int", "Version", "The gizmo version the last publish wrote."),
        ):
            self.add_parameter(
                Parameter(
                    name=parameter_name,
                    tooltip=tooltip,
                    type=parameter_type,
                    default_value=None,
                    allowed_modes={ParameterMode.PROPERTY},
                    ui_options={"display_name": display_name},
                )
            )
