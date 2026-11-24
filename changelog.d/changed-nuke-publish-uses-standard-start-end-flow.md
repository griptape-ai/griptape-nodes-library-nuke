- "Publish to Nuke Gizmo" now works with the standard `Start Flow` and `End Flow` nodes, and
  remembers the install path and published version on a hidden `Nuke Configuration` node that it
  adds to the workflow and saves on the first publish. Before, the version was only kept if you
  saved the workflow again yourself. Workflows that use `Nuke Start Flow` still open and publish,
  continuing from the version they last published.
  [#5179](https://github.com/griptape-ai/griptape-nodes-engine/issues/5179)
