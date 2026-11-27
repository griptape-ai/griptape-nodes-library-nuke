---
description: Runs an existing Nuke .nk script in the background and returns the images, video or frame sequences its Write nodes render.
when_to_use: "Use it when a comp you already built in Nuke should run inside a Griptape workflow, with Read nodes as inputs and Write nodes as outputs. Do not use it to build a gizmo from a workflow. Use Nuke Start Flow and Nuke End Flow for that."
---

Nuke Script runs a comp you already built in Foundry Nuke as one step of a Griptape workflow. A workflow is a set of connected nodes in Griptape Nodes. A comp is saved as a Nuke script, a `.nk` file. The node renders the script in the background, without opening Nuke's window, and passes the rendered images, video or frame sequences to the next node.

## When to use it

You have a `.nk` script and want a workflow to feed it plates, change a few knobs and collect the render. A knob is a setting on a Nuke node, such as the white point on a Grade.

The script decides what the node looks like. In Nuke you mark which Read nodes (they load files into the comp) are inputs and which Write nodes (they render files out of the comp) are outputs. The node grows a matching input or output for each one. You make the marks with the Annotator, a panel inside Nuke. Exposing a knob in the Annotator adds a control for it on the node.

## What it needs

- A Foundry Nuke installation and license. See [Setting up Nuke](../guides/nuke-setup.md).
- A saved `.nk` script with a `.gt.json` file beside it, with Read nodes marked as inputs and Write nodes as outputs. The Annotator panel writes the `.gt.json` file when you mark nodes. A script with no `.gt.json` file still runs and reports "Render complete.", but the node has no inputs or outputs. See [The Griptape Annotator panel](../guides/annotator-panel.md).

## Example

A comp artist has `hero_grade.nk`: one Read node called `plate`, a Grade called `Grade1`, and a Write node called `beauty`. To run it from a workflow:

1. Set `script_path` to `hero_grade.nk`.
1. Click **Open in Nuke**.
1. In Nuke, open **Panels > Griptape Annotator**. Mark `plate` as an input of type **ImageArtifact** and `beauty` as an output of type **ImageArtifact**. Select `Grade1` and tick the box beside `white` to expose it.
1. Back in Griptape Nodes, click **Refresh UI**. The node now has a `plate` input, a `beauty` output and a `white` control under a **Grade1** group.
1. Connect a plate to `plate`, set `frame_start` and `frame_end`, and run. The rendered image is on `beauty`.

For where the render is saved and what the errors mean, see [How a Nuke Script run works](../guides/how-a-run-works.md).

## Parameters

### exec_in

Shown as **Flow In**. Connect the node that runs before this one.

### exec_out

Shown as **Succeeded**. The workflow continues from here when the run finishes without error.

### failure

Shown as **Failed**. The workflow continues from here when Nuke exits with an error. See [How a Nuke Script run works](../guides/how-a-run-works.md).

### script_path

Shown as **Script Path (.nk)**. The path to the Nuke script. It can use project macros such as `{workspace_dir}`, a leading `~`, and workflow variables. A path that is not absolute is taken from the folder of the saved workflow. In a workflow template that ships inside a node library, start the path with `{library_dir}` to point at a file in that library's folder. Setting the path rebuilds the inputs, outputs and controls from the script's `.gt.json` file.

### nuke_installation

Shown as **Nuke Version**. Pick the Nuke installation to run, from the copies of Nuke installed on this machine. The list starts on the first entry and is filled in when you add the node and when you click **Refresh UI**. With nothing found the list says "(none configured)". See [Setting up Nuke](../guides/nuke-setup.md).

### frame_start

Shown as **Frame Start**. The first frame to render. It is 1001 until you change it. Negative frames are used as entered.

### frame_end

Shown as **Frame End**. The last frame to render. It is 1001 until you change it. The range applies to every output.

### open_in_nuke

Shown as **Open in Nuke**. Starts Nuke in its normal window with the script open and the Griptape Annotator panel available, so you can mark inputs, outputs and knobs. Any control values you have set are applied to the script first. Nuke keeps running on its own after you click. For the messages, see [How a Nuke Script run works](../guides/how-a-run-works.md#messages-from-the-buttons).

### refresh_ui

Shown as **Refresh UI**. Re-reads the installations and the `.gt.json` file. Click it after you annotate in Nuke or install a new Nuke version. The message is "UI refreshed." or, when there is no script to read, "Installation choices refreshed."

### nuke_executable

Shown as **Nuke Executable (override)**, in the **Advanced** group, which starts collapsed. A full path to a Nuke program. **Open in Nuke** always uses it. Renders and baked copies use it only when the **Nuke Version** list says "(none configured)", because a Nuke Version is always selected once any Nuke is found. See [Choosing which Nuke runs](../guides/nuke-setup.md#choosing-which-nuke-runs).

### baked_script_path

Shown as **Baked Script Output Path**, in the **Advanced** group. The `.nk` file that **Save Baked Copy** writes. An existing file at that path is replaced.

### save_baked_copy

Shown as **Save Baked Copy**, in the **Advanced** group. Opens the script in the background, applies the inputs and control values you have set, points the marked Write nodes at the output paths in the outputs folder of your Griptape Nodes project, and saves the result to `baked_script_path` without rendering. Use it to hand a comp artist a script with the workflow's inputs and control values already applied. See [Baked copies](../guides/how-a-run-works.md#baked-copies).

### was_successful

Shown in the **Status** group. True after a run that finishes without a Nuke error, false after a Nuke error.

### result_details

Shown in the **Status** group. "Render complete." after a successful run. After a Nuke error it holds the "FAILURE: Nuke exited with return code" message described in [How a Nuke Script run works](../guides/how-a-run-works.md).

## Edge cases

- A frame value of 0 is treated as unset and becomes 1001, so setting `frame_start` or `frame_end` to 0 uses frame 1001.
- Decimal controls accept values from -10 to 10 only. Whole-number controls have no limit.
- When a **Nuke Version** is selected, renders and baked copies ignore `nuke_executable`, but a render still needs the path to exist.
- If you save the `.nk` after annotating it, the sidecar is stale. A run after reopening the workflow sets no inputs, renders no outputs, and still reports "Render complete." Click **Refresh UI** first. See [When the script changes](../guides/annotator-panel.md#when-the-script-changes).
- Knobs exposed on a node that is marked as an input or output do not appear as controls.
- Outputs marked `ThreeDUrlArtifact` are skipped and stay empty.
