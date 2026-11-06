---
name: nuke-render-submission
description: Render a Nuke comp for dailies the Aurora way, versioning up first and writing the dailies note. Use when asked to render, submit, or send a Nuke comp to dailies or review.
---

# Nuke render submission

Renders for dailies follow these steps, in order. Don't skip any.

1. Run the `nuke-comp-review` checks first. If any fail, stop and show the artist the failures
   instead of rendering.
2. Call `NukeSaveNewVersionRequest` so the render never overwrites an earlier version.
3. Call `NukeRenderRequest` on the comp Write node with the full script frame range. Never
   render a partial range for dailies.
4. Write the dailies note using the template in `references/dailies-note.md` and show it to the
   artist.
