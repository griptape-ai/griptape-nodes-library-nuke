---
description: Marks the start of a workflow that you will publish as a Nuke gizmo.
when_to_use: "Use it as the first node of a workflow you plan to publish with Publish to Nuke Gizmo. Do not use it for workflows that stay in Griptape Nodes."
---

Nuke Start Flow marks the first node of a workflow that you want to use from inside Nuke. A workflow is a set of connected nodes in Griptape Nodes. When you publish it with **Publish to Nuke Gizmo**, the workflow becomes a gizmo, which is a custom node you add to the node graph in Nuke. The parameters you add to this node become the gizmo's controls. See [Publishing a workflow as a gizmo](../guides/publishing-a-gizmo.md).

## When to use it

You have built a workflow that should become a gizmo you can drop into a Nuke script. Start it with this node.

The publish step stops with the message "No NukeStartFlow node found in the workflow." if the workflow has no Nuke Start Flow node.

## What it needs

- Nothing to run it. It has no Nuke requirement of its own.
- A Nuke installation, to use the published gizmo. See [Setting up Nuke](../guides/nuke-setup.md).
- Pair it with [Nuke End Flow](NukeEndFlow.md) at the other end of the workflow.

## Example

You are wrapping a style-transfer workflow for the comp team. Add a Nuke Start Flow, then use its add-parameter control to add an `image` parameter for the plate and a `strength` number. After publishing, the gizmo in Nuke has an input for the plate and a `strength` knob (a number control), filled in with the values you had set when you published.

## Parameters

Each parameter you add becomes a control, called a knob in Nuke, on the **Inputs** tab of the published gizmo. The control is labelled with the parameter's display name, or with its name in capitalised words when it has no display name.

| Parameter | Knob on the gizmo |
|-----------|-------------------|
| Text | Text knob |
| Whole number | Whole-number knob |
| Decimal number | Decimal-number knob |
| True/false | Checkbox |
| A parameter with a list of choices | Menu |
| JSON or CSV | Multi-line text knob |
| Image, video, audio and file | A file path knob, and an input on the gizmo that you connect in the Nuke node graph |

Text, JSON, CSV and file path knobs also get a **Link...** button that fills the knob from the gizmo's name, the script's folder, the script's name, the current frame, or another node's knob.

When you run the gizmo:

- A connected video input renders the whole frame range of the connected input to a temporary movie.
- A connected image input renders the current frame to a temporary JPEG.
- An input with nothing connected uses its file path knob.

### exec_out

Shown as **Flow Out**. The only parameter that exists by default. Connect it to the first node of the workflow.
