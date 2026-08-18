"""Shared constants and naming helpers for the Nuke gizmo publish pipeline."""

from __future__ import annotations

import re

# Directory name for griptape artifacts inside the Nuke install dir (e.g. ~/.nuke/griptape/)
GRIPTAPE_DIR_NAME = "griptape"

# Marker comment appended to the pluginAddPath line in init.py for idempotent detection
INIT_MARKER = "# griptape-plugin-path"

# Filename of the run-button script copied into each companion directory
RUN_BUTTON_FILENAME = "run_button.py"

# Directory name (relative to the .nk script) where workflow outputs land when the
# gizmo's Output Directory knob is left blank. Stamped into the bundled project.yml
# at publish time and quoted in the gizmo's Run tab help text — shared here so the
# documented default and the actual default cannot drift apart.
OUTPUTS_DIR_NAME = "griptape_outputs"

# Prefix for the hidden companion knob that stores a Link button's TCL expression
# (the visible knob shows the evaluated value). Kept in sync with the local copy
# in the bundled tcl_utils.py, which cannot import this module at runtime.
GT_EXPR_PREFIX = "_gt_expr_"

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
