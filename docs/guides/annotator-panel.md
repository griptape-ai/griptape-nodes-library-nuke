---
title: The Griptape Annotator panel
description: How to mark Read and Write nodes as inputs and outputs, and expose knobs, in Nuke.
---

Read this page when you are preparing a `.nk` script for the Nuke Script node, or when the node shows the wrong inputs, outputs or controls.

The panel writes your choices to a `.gt.json` file beside the script, with the same name. The Nuke Script node builds its inputs, outputs and controls from that file. A script with no `.gt.json` file still runs, but the node has no inputs or outputs.

## Opening the panel

Click **Open in Nuke** on the Nuke Script node. Nuke opens the script with the panel available. In Nuke, choose **Panels > Griptape Annotator**. A **Refresh** button at the top re-reads the open script. Save the `.nk` script before you annotate it.

An input or output is named after its Nuke node in lower case, so a Read node called `Plate` becomes an input called `plate`.

## The Annotate tab

The tab lists every node in the script. Inputs are marked with an arrow pointing in (`→`) and outputs with an arrow pointing out (`←`).

- **Mark as Input** is available only when a Read node is selected. It asks for **ImageArtifact**, **VideoUrlArtifact** or **Sequence**.
- **Mark as Output** is available on any node. It asks for **ImageArtifact**, **VideoUrlArtifact**, **Sequence** or **ThreeDUrlArtifact**.
- **Clear Role** removes the mark from the selected node.
- Selecting a node shows its knobs on the right. Tick a knob's box to expose it as a control, and clear the box to stop exposing it.

Marked nodes get a green tile colour in the Node Graph. Nodes with exposed knobs get purple.

Each mark, clear and tick is written to the `.gt.json` file at once. There is no Save button for them. If the script has not been saved, the panel asks you to save it first and writes nothing.

The same actions are in right-click menus. Right-click inside a node's properties panel and choose **Griptape > Mark as Input**, **Mark as Output** or **Clear Griptape Role**. Right-click a knob's animation button and choose **Griptape > Expose Knob** or **Un-expose Knob**.

The menus differ from the panel in two ways. **Griptape > Mark as Input** is not limited to Read nodes, so mark only Read nodes as inputs. Marking or clearing a node from a right-click does not recolour its tile or refresh the panel until the panel refreshes. Expose and Un-expose do refresh the panel.

## The Overview tab

The tab shows a **Sidecar** line that reads "current" or "stale — script changed since annotation", and a list of the inputs, outputs and exposed knobs. An **Advanced** section holds the raw `.gt.json` text with a **Save Raw JSON** button, which checks that the text is valid JSON before it writes it.

## Exposed knobs

Knobs you expose appear on the Nuke Script node as controls, grouped under the name of the Nuke node they belong to and labelled with the knob's name. A control left empty uses the value saved in the script. A value you set replaces the knob's value for the run.

Knobs exposed on a node that is itself marked as an input or output do not appear as controls. Expose knobs on other nodes.

| Nuke knob | Control |
|-----------|---------|
| Decimal number, array and RGBA colour knobs | Number with a slider from -10 to 10 |
| Whole number | Number |
| Checkbox | Toggle |
| Anything else, including RGB colour, XY, menu, file and text knobs | Text |

A decimal control accepts values from -10 to 10. A value outside that range is rejected with a message such as "Attempted to set 'Grade1_white' to 11. Failed because it must be between -10.0 and 10.0." Whole-number controls have no limit.

A text value that reads as a number, such as `007`, is sent to Nuke as the number `7`.

If Nuke cannot apply a value, or the node it belongs to is gone from the script, the render continues with the value saved in the script. Nuke notes this in its own log, which the node shows only if the run fails.

## When the script changes

The `.gt.json` file stores a fingerprint of the `.nk` file. If you save the `.nk` after annotating it, the Overview tab shows the sidecar as stale and the node prints a warning that the file may be out of date. **Refresh UI** and setting `script_path` still read the file and build the inputs, outputs and controls from it.

When you reopen a workflow, a run ignores a `.gt.json` file that is out of date. No inputs are set, no outputs are rendered, and the node still reports "Render complete." Click **Refresh UI** before you run, or open the script in Nuke and mark an input, output or knob again to bring the file up to date.

If you rename or delete a Nuke node that an annotation points to, that input, output or knob is skipped. The run can still finish as a success, with that output empty.
