"""Publish-time options provider for the Nuke publisher.

Called by the engine when the frontend opens the publish dialog for the Nuke publisher.
Returns the fields to display and pre-populates them from saved publish_config metadata
on the NukeStartFlow node (if available).
"""

from __future__ import annotations

import logging
from pathlib import Path

from griptape_nodes.retained_mode.events.flow_events import GetTopLevelFlowRequest, GetTopLevelFlowResultSuccess
from griptape_nodes.retained_mode.events.workflow_events import (
    GetPublishOptionsRequest,
    GetPublishOptionsResultSuccess,
    PublishOptionField,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from publish_gizmo.nuke_discovery import (
    GIZMO_INSTALL_CUSTOM,
    compute_gizmo_install_path_choices,
    default_gizmo_path,
    discover_nuke_install_roots_and_map,
    normalize_path_str,
)

logger = logging.getLogger(__name__)


def _find_nuke_start_flow_node(workflow_name: str):  # noqa: ANN202
    """Return the NukeStartFlow node from the top-level flow, or None."""
    result = GriptapeNodes.handle_request(GetTopLevelFlowRequest())
    if not isinstance(result, GetTopLevelFlowResultSuccess) or result.flow_name is None:
        return None
    control_flow = GriptapeNodes.FlowManager().get_flow_by_name(result.flow_name)
    for node in control_flow.nodes.values():
        if node.__class__.__name__ == "NukeStartFlow":
            return node
    return None


def get_nuke_publish_options(request: GetPublishOptionsRequest) -> GetPublishOptionsResultSuccess:
    """Build the list of fields for the Nuke publish dialog."""
    current: dict = request.current_selections or {}

    # If the caller sent no selections, try to restore the last saved publish_config
    # from the NukeStartFlow node so the dialog is pre-populated.
    if not current:
        start_flow = _find_nuke_start_flow_node(request.workflow_name)
        if start_flow is not None:
            saved = start_flow.metadata.get("publish_config")
            if saved and isinstance(saved, dict):
                current = saved

    nuke_roots, root_to_exe = discover_nuke_install_roots_and_map()

    # Resolve the currently selected nuke installation
    saved_nuke = current.get("nuke")
    if saved_nuke and normalize_path_str(saved_nuke) in nuke_roots:
        selected_nuke: str | None = normalize_path_str(saved_nuke)
    else:
        selected_nuke = nuke_roots[0] if nuke_roots else None

    nuke_choices = nuke_roots if nuke_roots else ["No Nuke installations found"]

    # Compute gizmo path choices based on the selected nuke
    gizmo_candidates = compute_gizmo_install_path_choices(selected_nuke, root_to_exe)
    gizmo_choices = gizmo_candidates + [GIZMO_INSTALL_CUSTOM]

    # Resolve the saved gizmo install path selection
    saved_gizmo = current.get("gizmo_install_path")
    if saved_gizmo == GIZMO_INSTALL_CUSTOM:
        selected_gizmo = GIZMO_INSTALL_CUSTOM
    elif saved_gizmo:
        saved_norm = normalize_path_str(saved_gizmo)
        if saved_norm in gizmo_candidates:
            selected_gizmo = saved_norm
        else:
            selected_gizmo = default_gizmo_path(gizmo_choices)
    else:
        selected_gizmo = default_gizmo_path(gizmo_choices)

    custom_gizmo_default = current.get("custom_gizmo_path", str(Path.home() / ".nuke"))
    custom_hidden = selected_gizmo != GIZMO_INSTALL_CUSTOM

    saved_format = current.get("publish_format", "livegroup")

    fields = [
        PublishOptionField(
            name="publish_format",
            label="Publish Format",
            field_type="dropdown",
            tooltip=(
                "LiveGroup: publishes as a versioned .nk file that Nuke can reload when updated (recommended). "
                "Gizmo: publishes as a static .gizmo file."
            ),
            choices=["livegroup", "gizmo"],
            default_value=saved_format,
            depends_on=None,
        ),
        PublishOptionField(
            name="nuke",
            label="Nuke Installation",
            field_type="dropdown",
            tooltip=(
                "Nuke install location (version folder under /Applications, Program Files, etc.). "
                "The main Nuke binary for that install is used automatically."
            ),
            choices=nuke_choices,
            default_value=selected_nuke,
            depends_on=None,
        ),
        PublishOptionField(
            name="gizmo_install_path",
            label="Gizmo Install Path",
            field_type="dropdown",
            tooltip=(
                "Directory where the gizmo will be installed. Choose 'Custom path\u2026' to enter a path manually."
            ),
            choices=gizmo_choices,
            default_value=selected_gizmo,
            depends_on="nuke",
        ),
        PublishOptionField(
            name="custom_gizmo_path",
            label="Custom Gizmo Path",
            field_type="file_picker",
            tooltip="Directory where the gizmo should be installed (shown when 'Custom path\u2026' is selected above).",
            choices=None,
            default_value=custom_gizmo_default,
            depends_on="gizmo_install_path",
            hidden=custom_hidden,
        ),
    ]

    return GetPublishOptionsResultSuccess(
        fields=fields,
        result_details="Nuke publish options resolved successfully.",
    )
