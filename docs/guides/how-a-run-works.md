---
title: How a Nuke Script run works
description: What the Nuke Script node does during a run, where its outputs are saved, and what its error messages mean.
---

Read this page when you want to know where a render ends up, how inputs are handled, or what an error message means.

## What happens in a run

The node starts Nuke in the background, opens your `.nk`, points each marked Read node at the file you supplied, applies any knob values you set, and renders each marked Write node over the frame range. Your `.nk` file is not changed. Nuke's proxy mode is switched off for the run.

The render range applies to every output. An image output is one file. Mark the output as a Sequence to keep every frame in the range.

## Where outputs are saved

Each output is saved in the project's outputs folder. With the default project layout:

| Marked as | You get | Where and how it is named |
|-----------|---------|---------------------------|
| ImageArtifact | One image | PNG, whatever file type the Write node was set to. Saved as `image_v001.png` in `outputs/images`. Each run saves a new number. |
| VideoUrlArtifact | One video | `.mp4`. Saved as `video_v001.mp4` in `outputs/videos`. Each run saves a new number. |
| Sequence | A frame sequence | PNG frames named `frame_####.png`, with four-digit numbers, in `outputs/images/<node name>/<output name>_v001`. A rerun renders over the same frames. |

3D geometry is not rendered yet. The Annotator panel lets you mark an output as `ThreeDUrlArtifact`, but the run skips it and the output stays empty. The run does not report this as an error. Do not use it.

Outputs appear in an **Outputs** group once the script has marked Write nodes. They fill in after a successful run.

## Inputs

Each Read node you mark as an input becomes an input on the node. It takes a file path (text), an image, a video, a blob or a frame sequence.

- An image or video that lives at a web address is downloaded before the render. Each download waits up to 30 seconds for a response.
- A frame sequence keeps its own first and last frame. If none of its frames fall inside `frame_start` to `frame_end`, the Griptape Nodes log shows the warning "Input sequence 'plate' covers frames 1-10 but the render range is 2001-2003; no input frame falls inside the render." and the render continues.
- A frame sequence with no frames stops the run. See below.
- Connect every input you marked. An input left empty gives its Read node an empty file path.

## When something goes wrong

The run does not start when:

- `script_path` is empty. The message is "script_path is required".
- The script is not at the path. The message is "Script not found: " followed by the full path.
- `script_path` uses a macro or variable that cannot be resolved. The message is "Could not resolve Script Path '...': unknown variable(s) " followed by the names.
- No Nuke is set up. The message is "nuke_executable is not set and nuke.executable engine setting is empty".
- The Nuke program is missing. The message is "Nuke executable not found: " followed by the path.

If Nuke starts and then exits with an error, `was_successful` is false and `result_details` starts with "FAILURE: Nuke exited with return code" followed by the last 20 lines of Nuke's log. A failed render of any one output makes the whole run fail, and none of the outputs are returned.

If something is connected to the **Failed** output, the workflow carries on down that path after a Nuke error. If not, the workflow stops with the same message. The errors below stop the workflow whether or not **Failed** is connected:

- A frame sequence input with no frames. The message is "Input 'plate' received a sequence with no frames (range 0 to -1). Check the upstream scan: the pattern matched nothing on disk."
- A Sequence output with no frames in the render range. The message is "No frames found for sequence at" followed by the path.

## Baked copies

**Save Baked Copy** writes the script the workflow would run, without rendering.

- An input left empty keeps the file path stored in the script.
- Inputs that had to be downloaded are saved in the project's outputs folder instead of a temporary folder, so the baked copy can still find them.

## Messages from the buttons

**Open in Nuke**:

- "Script not found: " followed by the path, when the script is missing.
- "script_path is not set", when the path is empty.
- "Nuke executable not found: " followed by the path, when the Nuke program is not found.

**Save Baked Copy**:

- "Set 'Baked Script Output Path' first." when the path is empty.
- "Baked copy saved to:" followed by the path on success.
- "Bake failed (exit N):" followed by the last 10 lines of Nuke's log when Nuke exits with an error.
