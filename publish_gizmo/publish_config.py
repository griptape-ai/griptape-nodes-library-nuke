"""Settings the last Nuke publish remembered.

The engine resolves this from the workflow's Nuke Configuration node, or, for a workflow published
before that node existed, from a Start node's legacy ``publish_config`` metadata -- either way it
arrives here as ``configuration``, so this module does not have to tell the two apart.
"""

from __future__ import annotations

from typing import Any

GIZMO_INSTALL_PATH = "gizmo_install_path"
CUSTOM_GIZMO_PATH = "custom_gizmo_path"
GIZMO_PATH = "gizmo_path"
VERSION = "version"


def saved_publish_config(configuration: dict[str, Any] | None) -> dict[str, Any]:
    """The settings the last publish remembered, or an empty dict if this workflow was never published."""
    return configuration or {}
