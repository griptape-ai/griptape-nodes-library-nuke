- **Breaking:** Nuke acts only on the workflow it loaded. With none loaded, execute, the
  parameter-value verbs, execution state and cancel report that instead of driving the workflow
  open in the editor. A host that drove an editor's workflow without loading it must send
  `NukeLoadWorkflowRequest` for that workflow first.
