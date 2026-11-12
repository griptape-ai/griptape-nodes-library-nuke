"""Settings the last Nuke publish remembered, from the Nuke Configuration node or a legacy Start node."""

from __future__ import annotations

from typing import Any

from griptape_nodes.exe_types.node_types import StartNode
from griptape_nodes.retained_mode.events.flow_events import GetTopLevelFlowRequest, GetTopLevelFlowResultSuccess
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

GIZMO_INSTALL_PATH = "gizmo_install_path"
CUSTOM_GIZMO_PATH = "custom_gizmo_path"
GIZMO_PATH = "gizmo_path"
VERSION = "version"


def saved_publish_config(configuration: dict[str, Any] | None) -> dict[str, Any]:
    """The settings the last publish remembered, or an empty dict if this workflow was never published."""
    if configuration is not None:
        return configuration
    # Published before the Nuke Configuration node existed; the next publish moves these onto it.
    return _legacy_publish_config() or {}


def _legacy_publish_config() -> dict[str, Any] | None:
    result = GriptapeNodes.handle_request(GetTopLevelFlowRequest())
    if not isinstance(result, GetTopLevelFlowResultSuccess) or result.flow_name is None:
        return None
    control_flow = GriptapeNodes.FlowManager().get_flow_by_name(result.flow_name)
    for node in control_flow.nodes.values():
        if not isinstance(node, StartNode):
            continue
        saved = node.metadata.get("publish_config")
        if isinstance(saved, dict) and saved:
            return saved
    return None
