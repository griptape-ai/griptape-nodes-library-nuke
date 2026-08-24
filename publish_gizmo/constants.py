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
# gizmo's Output Directory knob is left blank. Quoted in the gizmo's Run tab help
# text — shared here so the documented default and the actual default cannot drift
# apart.
OUTPUTS_DIR_NAME = "griptape_outputs"

# Publisher-source filename -> companion-bundle filename, for the scripts copied
# into every companion directory at publish time.
BUNDLED_SCRIPTS = {
    "nuke_workflow_runner.py": "run_workflow.py",
    RUN_BUTTON_FILENAME: RUN_BUTTON_FILENAME,
    "register_libraries_script.py": "register_libraries_script.py",
    "output_protocol.py": "output_protocol.py",
    "tcl_utils.py": "tcl_utils.py",
    "output_paths.py": "output_paths.py",
}

# Matches the per-version subdirectories (v1, v2, ...) inside a companion directory.
# The digit class keeps it from also matching a future non-version entry starting
# with "v".
VERSION_DIR_GLOB = "v[0-9]*"

# Entries a re-publish must carry across the staged rebuild rather than discard.
#
# The version subdirs are meant to accumulate -- each published version keeps its
# own workflow file. The other two are run artifacts, not publish artifacts: for a
# gizmo driven from an unsaved .nk there is no script directory to use as the
# workspace, so the runner falls back to the companion and the engine writes
# griptape_outputs/ and staticfiles/ inside the bundle. Deleting an artist's
# generated frames on re-publish would be worse than the staleness the rebuild
# fixes, so they survive it.
PRESERVED_ON_REPUBLISH = [VERSION_DIR_GLOB, OUTPUTS_DIR_NAME, "staticfiles"]

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
