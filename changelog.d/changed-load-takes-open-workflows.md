- Loading a workflow from Nuke uses the copy an editor tab already has open, unsaved edits
  included, instead of reloading it from disk. A failed load leaves Nuke's previous workflow
  loaded, and the next load closes it only if Nuke opened it.
