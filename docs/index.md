---
title: Foundry Nuke
---

This library connects Griptape Nodes to Foundry Nuke, the compositing application. It works in two directions.

- A comp you already built in Nuke can run inside a Griptape workflow. A workflow is a set of connected nodes in Griptape Nodes. The comp is a Nuke script, a `.nk` file, and it runs in the background without opening Nuke's window.
- A Griptape workflow can be packaged as a gizmo. A gizmo is a custom node that you add to the node graph in Nuke and use like any other Nuke node.

The nodes are in the **Foundry Nuke** category of the node picker.

## Where to start

- To run a `.nk` script from a workflow, use [Nuke Script](nodes/NukeScriptNode.md). Read nodes (which load images into Nuke) that you mark become inputs. Write nodes (which render images out of Nuke) that you mark become outputs. Knobs (the settings on a Nuke node) that you expose become controls.
- To start a workflow that you will publish as a gizmo, use [Nuke Start Flow](nodes/NukeStartFlow.md). Parameters you add become inputs on the gizmo.
- To end a workflow that you will publish as a gizmo, use [Nuke End Flow](nodes/NukeEndFlow.md). Parameters you add become results on the gizmo.
- To mark the inputs, outputs and knobs in your script, using a panel inside Nuke, read [The Griptape Annotator panel](guides/annotator-panel.md).
- To see where a render is saved and what the errors mean, read [How a Nuke Script run works](guides/how-a-run-works.md).
- To publish a workflow to Nuke and run the gizmo, read [Publishing a workflow as a gizmo](guides/publishing-a-gizmo.md).
- If Nuke is not listed or cannot find its license, read [Setting up Nuke](guides/nuke-setup.md).

## How they fit together

Nuke Script and the two flow nodes do different jobs and are usually not in the same workflow.

- Running a comp from a workflow: connect your sources to a Nuke Script node, set the frame range and run. The rendered image, video or frame sequence comes out of its outputs for the next node.
- Using a workflow from Nuke: put a Nuke Start Flow at the beginning and a Nuke End Flow at the end, and build the workflow between them. Then publish it as a gizmo.
