---
title: Publishing a workflow as a gizmo
description: How to publish a workflow to Nuke, where the files go, and how to run the gizmo.
---

Publishing turns a Griptape workflow into a gizmo. A workflow is a set of connected nodes in Griptape Nodes, for example one that restyles an image. A gizmo is a custom node that you add to the node graph in Nuke and use like any other Nuke node. When you run the gizmo, it runs the workflow.

The workflow must start with a [Nuke Start Flow](../nodes/NukeStartFlow.md) node and end with a [Nuke End Flow](../nodes/NukeEndFlow.md) node. The parameters you add to the start node become the gizmo's controls, and the ones you add to the end node become its results. This page covers how to publish, where the files go, and what to check when the gizmo does not show up in Nuke.

## Publish

1. Build a workflow that starts with a Nuke Start Flow and ends with a Nuke End Flow, and save it.
1. Choose **Publish to Nuke Gizmo**. Pick a **Gizmo Install Path**. The list holds `~/.nuke` (Nuke's per-user folder), then every folder in the `NUKE_PATH` environment variable (the list of folders where Nuke looks for plugins and gizmos), then **Custom path…**. `~/.nuke` is selected unless you saved a different choice. **Custom path…** shows a **Custom Gizmo Path** field, and a relative path there is taken from the Griptape Nodes workspace folder. A folder that does not exist is created. When you publish a workflow that was published before, **Update Mode** offers **Update current version (v1)** or **Publish new version (v2)**, with the numbers following the last publish.
1. Restart Nuke once after the first publish into an install folder. The publish adds a line to that folder's `init.py`, a startup script Nuke runs when it opens. The line puts its `griptape` subfolder on Nuke's plugin path. Whatever else `init.py` holds is kept. Nuke reads `init.py` only at startup. Until then Nuke has no **Griptape** menu. Each install folder needs its own restart.
1. In Nuke, create the gizmo from **Nodes > Griptape** on the Nodes toolbar. The entry is named after the workflow file with underscores turned into spaces and each word capitalised, so `my_workflow` is **My Workflow**. One published version is a single entry. Several versions of the same workflow are grouped under a submenu with that name, with an entry for each version such as **v1** and **v2**.
1. Later publishes into the same folder need no restart. If the menu does not show the new version, for example on a network drive, choose **Griptape > Refresh Griptape Gizmos** from Nuke's main menu bar.

The publish stops with the message "No NukeStartFlow node found in the workflow." if the workflow has no Nuke Start Flow node.

## What gets written

The publish writes a `griptape` folder inside the install folder. It holds a versioned gizmo such as `my_workflow_v01.gizmo` (the version number has two digits), a `menu.py` for the **Griptape** menu, and a folder named after the workflow with the files needed to run it, including one `v1`, `v2` folder per published version. The `.gizmo` file is a node type to create in Nuke's Node Graph, not a file to open.

## Running the gizmo

The gizmo has three tabs.

- **Run** holds an **Output Directory** field and the **Run Workflow** button.
- **Inputs** holds one control for each parameter on Nuke Start Flow. Each control is a knob, which is a setting on a Nuke node.
- **Outputs** shows the results from Nuke End Flow.

The first **Run Workflow** on a computer builds a Python environment for the gizmo and takes a few minutes. Later runs start faster.

When the gizmo runs, the files the workflow saves go in a `griptape_outputs` folder beside the `.nk` script. A relative **Output Directory** is taken from the `.nk` script's folder. The first file with a given name keeps it, and later files with the same name get `_v0001`, `_v0002` and so on, so `image.png` is followed by `image_v0001.png`. Other files from the run go in a hidden `.griptape` folder in the same place. If the script has never been saved, both go inside the gizmo's own folder, the one named after the workflow, instead.
