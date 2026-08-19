"""Generate .nk test fixtures for script_parser unit tests.

Run once via:
    /path/to/Nuke -t scripts/generate_test_fixtures.py

The resulting files in tests/unit/fixtures/ are committed to the repo.
Unit tests read them directly — Nuke is never invoked by the test suite.

NOTE: nuke.scriptNew() does not clear node state between calls in a single
terminal session. This script clears all nodes explicitly between fixtures
by iterating nuke.allNodes() and deleting each one (see _clear()).

Regenerating tests/integration/fixtures/canary/canary_workflow.nk is a two-step process,
because the gizmo node type must exist on Nuke's plugin path before this script can
create an instance of it, and publishing a gizmo needs griptape_nodes -- unavailable
inside Nuke's bundled Python:

    1. uv run python -m tests.integration.fixtures.canary.publish_canary_gizmo --install-dir /tmp/canary_gizmo_fixture
       (from the repository root, so -m puts it on sys.path and the imports resolve)
    2. CANARY_GIZMO_INSTALL_DIR=/tmp/canary_gizmo_fixture/install/griptape \
           /path/to/Nuke -t scripts/generate_test_fixtures.py

Step 2 is skipped (with a printed note) when CANARY_GIZMO_INSTALL_DIR is unset, so
regenerating the other fixtures above doesn't require it. Any Nuke version at or
above the one that originally wrote canary_workflow.nk can be used to regenerate it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import nuke

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "publish_gizmo"))
from constants import versioned_node_name  # noqa: E402

FIXTURES_DIR = _REPO_ROOT / "tests" / "unit" / "fixtures"


def _add_gt_knob(node, knob_name, label, value):
    k = nuke.String_Knob(knob_name, label)
    node.addKnob(k)
    node[knob_name].setValue(value)


def _save(filename):
    path = os.path.join(FIXTURES_DIR, filename).replace("\\", "/")
    nuke.scriptSave(path)
    print(f"wrote {path}")


def _clear():
    for node in list(nuke.allNodes()):
        nuke.delete(node)


# --- fixture 1: annotated_read_write.nk ---
# A Read node marked as gt input and a Write node marked as gt output.

_clear()

read = nuke.createNode("Read", inpanel=False)
read["name"].setValue("GradeInput")
_add_gt_knob(read, "gt_role", "Griptape Role", "input")
_add_gt_knob(read, "gt_name", "Griptape Name", "source_image")
_add_gt_knob(read, "gt_type", "Griptape Type", "ImageArtifact")
_add_gt_knob(read, "gt_label", "Griptape Label", "Source Image")

write = nuke.createNode("Write", inpanel=False)
write["name"].setValue("GradeOutput")
write["file"].setValue("/tmp/placeholder.png")
write["file_type"].setValue("png")
_add_gt_knob(write, "gt_role", "Griptape Role", "output")
_add_gt_knob(write, "gt_name", "Griptape Name", "graded_image")
_add_gt_knob(write, "gt_type", "Griptape Type", "ImageArtifact")

_save("annotated_read_write.nk")

# --- fixture 2: exposed_knob.nk ---
# A Grade node with a gt_expose_white knob promoting Grade1.white (displayed
# as "Gain" in the Nuke UI; Python API name is "white").

_clear()

grade = nuke.createNode("Grade", inpanel=False)
grade["name"].setValue("Grade1")
grade["white"].setValue(1.2)
_add_gt_knob(grade, "gt_expose_white", "Expose: white (gain)", "Grade1.white")

_save("exposed_knob.nk")

# --- fixture 3: no_annotations.nk ---
# A plain Blur node with no gt_* knobs — baseline for the parser.

_clear()

blur = nuke.createNode("Blur", inpanel=False)
blur["name"].setValue("Blur1")
blur["size"].setValue(5.0)

_save("no_annotations.nk")

# --- fixture 4: constant_write.nk ---
# A Constant node feeding a Write node annotated as gt output.
# No input file required — used by the runner integration test.

_clear()

constant = nuke.createNode("Constant", inpanel=False)
constant["name"].setValue("Bg")

write = nuke.createNode("Write", inpanel=False)
write["name"].setValue("ConstantOutput")
write["file"].setValue("/tmp/placeholder.png")
write["file_type"].setValue("png")
_add_gt_knob(write, "gt_role", "Griptape Role", "output")
_add_gt_knob(write, "gt_name", "Griptape Name", "result")
_add_gt_knob(write, "gt_type", "Griptape Type", "ImageArtifact")

_save("constant_write.nk")

# --- fixture 5: tests/integration/fixtures/canary/canary_workflow.nk ---
# One instance of the published canary_workflow_v01 gizmo. See this script's module
# docstring for the two-step regeneration process; skipped when the gizmo hasn't
# been published to a known plugin path first.

_INTEGRATION_FIXTURES_DIR = _REPO_ROOT / "tests" / "integration" / "fixtures" / "canary"
_canary_gizmo_install_dir = os.environ.get("CANARY_GIZMO_INSTALL_DIR", "").replace("\\", "/")
_CANARY_GIZMO_NODE_TYPE = versioned_node_name("canary_workflow", 1)

if _canary_gizmo_install_dir:
    _clear()
    nuke.pluginAddPath(_canary_gizmo_install_dir)
    # pluginAddPath alone doesn't force a directory walk; nuke.plugins() does (same
    # trick the generated companion menu.py uses to pick up newly published gizmos).
    nuke.plugins(nuke.ALL, "*.gizmo")
    canary_node = nuke.createNode(_CANARY_GIZMO_NODE_TYPE, inpanel=False)
    canary_node["name"].setValue(f"{_CANARY_GIZMO_NODE_TYPE}_1")
    _canary_path = str(_INTEGRATION_FIXTURES_DIR / "canary_workflow.nk").replace("\\", "/")
    nuke.scriptSave(_canary_path)
    print(f"wrote {_canary_path}")
else:
    print(
        "CANARY_GIZMO_INSTALL_DIR not set; skipping tests/integration/fixtures/canary/canary_workflow.nk regeneration"
    )

print("fixtures 1-4 written to", FIXTURES_DIR)
sys.exit(0)
