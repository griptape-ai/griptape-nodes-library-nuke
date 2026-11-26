---
title: Foundry Nuke
---

This library connects Griptape Nodes to Foundry Nuke in two directions. A comp you already built in Nuke can run inside a Griptape workflow, and a Griptape workflow can be packaged as a gizmo you use from Nuke's node graph. The nodes are in the **Foundry Nuke** category of the node picker.

## Where to start

- To run a `.nk` script from a workflow, use [Nuke Script](nodes/NukeScriptNode.md). Marked Read nodes become inputs, marked Write nodes become outputs, and exposed knobs become controls.
- To start a workflow that you will publish as a gizmo, use [Nuke Start Flow](nodes/NukeStartFlow.md). Parameters you add become gizmo inputs.
- To end a workflow that you will publish as a gizmo, use [Nuke End Flow](nodes/NukeEndFlow.md). Parameters you add become gizmo results.
- To mark inputs, outputs and knobs in your script, read [The Griptape Annotator panel](guides/annotator-panel.md).
- To see where a render is saved and what the errors mean, read [How a Nuke Script run works](guides/how-a-run-works.md).
- To publish a workflow to Nuke and run the gizmo, read [Publishing a workflow as a gizmo](guides/publishing-a-gizmo.md).
- If Nuke is not listed or cannot find its license, read [Setting up Nuke](guides/nuke-setup.md).

## How they fit together

Nuke Script and the two flow nodes do different jobs and are usually not in the same workflow.

- Running a comp from a workflow: connect your sources to a Nuke Script node, set the frame range and run. The rendered image, video or frame sequence comes out of its outputs for the next node.
- Using a workflow from Nuke: put a Nuke Start Flow at the beginning and a Nuke End Flow at the end, and build the workflow between them. Then publish it as a gizmo.
