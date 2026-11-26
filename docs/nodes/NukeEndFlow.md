---
description: Marks the end of a workflow that you will publish as a Nuke gizmo, and collects the workflow's results.
when_to_use: "Use it as the last node of a workflow you plan to publish with Publish to Nuke Gizmo. Do not use it for workflows that stay in Griptape Nodes."
---

## When to use it

You have built a workflow that should become a gizmo you can drop into a Nuke script. End it with this node. Anything you add to it becomes a result on the gizmo.

## What it needs

- Nothing to run it. It has no Nuke requirement of its own.
- A Nuke installation, to use the published gizmo. See [Setting up Nuke](../guides/nuke-setup.md).
- Pair it with [Nuke Start Flow](NukeStartFlow.md) at the other end of the workflow.

## Example

The style-transfer workflow from [Nuke Start Flow](NukeStartFlow.md) ends here. Add an `image` parameter to the end node and connect the styled image to it. In Nuke, the gizmo shows that image on its Outputs tab, and it is displayed through a Read node inside the gizmo.

## Parameters

Each parameter you add becomes a read-only result on the gizmo's **Outputs** tab, with a **Copy Link** button beside it. The result is labelled with the parameter's display name, or with its name in capitalised words when it has no display name.

- Image, video, audio and file results are shown through a Read node inside the gizmo.
- When the workflow has more than one image, video, audio or file result, an **Active Output** menu on the Outputs tab picks which one the gizmo passes on.
- In a Nuke script, refer to a result with an expression such as `[value mygizmo_v01.caption_out]`. The knob name is the parameter name followed by `_out`.

### exec_in

Shown as **Succeeded**. Connect the last node of the workflow here when it succeeds.

### failed

Shown as **Failed**. Connect a node's failure output here to end the workflow on the failure path. The node records whether **Succeeded** or **Failed** was used.

### was_successful

Shows whether the workflow ended on the success path or the failure path. It is in the **Status** group, which starts collapsed. It stays inside Griptape Nodes and does not appear as a knob on the published gizmo.

### result_details

A message about how the workflow ended, in the **Status** group. Connect a text value to it. After a run it starts with `[SUCCEEDED]` or `[FAILED]`, followed on the next line by your message, or by "No details supplied by flow" when you gave none. It stays inside Griptape Nodes and does not appear on the published gizmo.
