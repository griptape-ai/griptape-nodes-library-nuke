"""Publish-time options provider for the Nuke publisher.

Called by the engine when the frontend opens the publish dialog for the Nuke publisher.
Returns the fields to display and pre-populates them from the settings the last publish
remembered (see ``publish_config.saved_publish_config``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from griptape_nodes.retained_mode.events.workflow_events import (
    GetPublishOptionsRequest,
    GetPublishOptionsResultSuccess,
    PublishFieldType,
    PublishOptionField,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from publish_gizmo.nuke_discovery import (
    GIZMO_INSTALL_CUSTOM,
    compute_gizmo_install_path_choices,
    default_gizmo_path,
    normalize_path_str,
)
from publish_gizmo.output_paths import absolutize
from publish_gizmo.publish_config import saved_publish_config

logger = logging.getLogger(__name__)


def get_nuke_publish_options(request: GetPublishOptionsRequest) -> GetPublishOptionsResultSuccess:
    """Build the list of fields for the Nuke publish dialog."""
    # With no selections yet, the dialog opens on what the last publish remembered.
    current: dict = request.current_selections or saved_publish_config(request.configuration)

    gizmo_candidates = compute_gizmo_install_path_choices()
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

    # Absolutized like the dropdown selection above, but anchored to the workspace rather
    # than via normalize_path_str, which would resolve a relative saved value against the
    # engine's working directory. Matches _resolve_gizmo_install_path so the dialog shows
    # the path the publish will actually use.
    saved_custom = current.get("custom_gizmo_path")
    custom_gizmo_default = (
        absolutize(str(saved_custom), str(GriptapeNodes.ConfigManager().workspace_path))
        if saved_custom
        else str(Path.home() / ".nuke")
    )
    custom_hidden = selected_gizmo != GIZMO_INSTALL_CUSTOM

    is_update = bool(current.get("gizmo_path") and current.get("version") is not None)

    fields = [
        PublishOptionField(
            name="gizmo_install_path",
            label="Gizmo Install Path",
            field_type=PublishFieldType.DROPDOWN,
            tooltip=(
                "Directory where the gizmo will be installed. Choose 'Custom path\u2026' to enter a path manually."
            ),
            choices=gizmo_choices,
            default_value=selected_gizmo,
            depends_on=None,
        ),
        PublishOptionField(
            name="custom_gizmo_path",
            label="Custom Gizmo Path",
            field_type=PublishFieldType.FILE_PICKER,
            tooltip="Directory where the gizmo should be installed (shown when 'Custom path\u2026' is selected above).",
            choices=None,
            default_value=custom_gizmo_default,
            depends_on="gizmo_install_path",
            hidden=custom_hidden,
        ),
    ]

    if is_update:
        saved_version = int(current["version"])
        next_version = saved_version + 1

        # Update mode selector prepended at the top of the dialog
        fields.insert(
            0,
            PublishOptionField(
                name="update_mode",
                label="Update Mode",
                field_type=PublishFieldType.DROPDOWN,
                tooltip=f"Currently published as v{saved_version} at {current.get('gizmo_path', '')}",
                choices=[
                    f"Update current version (v{saved_version})",
                    f"Publish new version (v{next_version})",
                ],
                default_value=f"Update current version (v{saved_version})",
                depends_on=None,
            ),
        )

        # Hidden fields pass version info through to the publisher via metadata
        fields.append(
            PublishOptionField(
                name="version",
                label="",
                field_type=PublishFieldType.TEXT,
                default_value=str(saved_version),
                hidden=True,
            )
        )
        fields.append(
            PublishOptionField(
                name="gizmo_path",
                label="",
                field_type=PublishFieldType.TEXT,
                default_value=current.get("gizmo_path", ""),
                hidden=True,
            )
        )

    return GetPublishOptionsResultSuccess(
        fields=fields,
        title="Update Published Gizmo" if is_update else None,
        button_label="Update" if is_update else None,
        result_details="Nuke publish options resolved successfully.",
    )
