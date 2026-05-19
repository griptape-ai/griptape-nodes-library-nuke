"""Generate .nk test fixtures for script_parser unit tests.

Run once via:
    /path/to/Nuke -t scripts/generate_test_fixtures.py

The resulting files in tests/unit/fixtures/ are committed to the repo.
Unit tests read them directly — Nuke is never invoked by the test suite.

NOTE: nuke.scriptNew() does not clear node state between calls in a single
terminal session. This script clears all nodes explicitly between fixtures
using nuke.selectAll() + nuke.delete().
"""

import os
import sys

import nuke

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "unit", "fixtures")


def _add_gt_knob(node, knob_name, label, value):
    k = nuke.String_Knob(knob_name, label)
    node.addKnob(k)
    node[knob_name].setValue(value)


def _save(filename):
    path = os.path.join(FIXTURES_DIR, filename).replace("\\", "/")
    nuke.scriptSave(path)
    print(f"wrote {path}")


def _clear():
    nuke.selectAll()
    nuke.delete()


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

print("all fixtures written to", FIXTURES_DIR)
sys.exit(0)
