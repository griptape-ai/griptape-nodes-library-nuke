---
name: nuke-comp-review
description: Review the artist's open Nuke comp against Aurora studio rules before it goes to dailies. Use when asked to check, review, QC, or sanity-check a Nuke script or comp.
---

# Nuke comp review

Use the Nuke library tools to inspect the open script. Read before you change anything.

1. Call `NukeGetScriptInfoRequest` to get the shot, version, and plate frame range.
2. Call `NukeListNodesRequest`, then `NukeGetNodeRequest` on every Read and Write node and on
   anything disabled.
3. Check each rule below and report the result as a table with columns **Check**, **Status**
   (pass or fail), and **Detail**. Name the node for every failure.
4. Offer to fix the failures. Don't change any knob until the artist says yes.

## Studio rules

| Check | Rule |
| --- | --- |
| Write format | Every Write node renders `exr` with `compression` set to `zip1`. |
| Write colorspace | Write nodes output `ACES - ACEScg`. Display transforms like sRGB are for review only. |
| Frame range | Each Write node's `first` and `last` match the script's frame range exactly. |
| Output naming | Write paths follow `<shot>_comp_v###/<shot>_comp_v###.####.exr`, with the version matching the script. |
| Disabled nodes | No node feeding a Write is disabled. A disabled node in the main pipe usually means a forgotten test. |
| Plate colorspace | Camera plates are read as `ACES - ACES2065-1`. CG and elements are read as `ACES - ACEScg`. |

When fixing the Write format, set `file_type` to `exr`, `compression` to `zip1`, and change the
`file` extension from `.png` to `.exr`.
