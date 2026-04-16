"""Shared constants and naming helpers for the Nuke gizmo publish pipeline."""

from __future__ import annotations

import re

# Directory name for griptape artifacts inside the Nuke install dir (e.g. ~/.nuke/griptape/)
GRIPTAPE_DIR_NAME = "griptape"

# Marker comment appended to the pluginAddPath line in init.py for idempotent detection
INIT_MARKER = "# griptape-plugin-path"

# Filename of the run-button script copied into each companion directory
RUN_BUTTON_FILENAME = "run_button.py"

# Regex that extracts (workflow_stem, version_int) from a versioned gizmo filename
VERSION_RE = re.compile(r"^(.+)_v(\d+)\.gizmo$")


def versioned_gizmo_filename(stem: str, version: int) -> str:
    """Return e.g. ``'my_workflow_v01.gizmo'``."""
    return f"{stem}_v{str(version).zfill(2)}.gizmo"


def versioned_node_name(stem: str, version: int) -> str:
    """Return the Nuke node class name, e.g. ``'my_workflow_v01'``."""
    return f"{stem}_v{str(version).zfill(2)}"


def versioned_gizmo_glob(stem: str) -> str:
    """Return a glob/``nuke.plugins`` pattern, e.g. ``'my_workflow_v*.gizmo'``."""
    return f"{stem}_v*.gizmo"
