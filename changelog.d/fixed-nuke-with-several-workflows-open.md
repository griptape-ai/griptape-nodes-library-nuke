- Nuke can load, read, set, run, and cancel its workflow while the engine has other workflows open,
  such as editor tabs, instead of failing with `WorkflowNotNamedError`. Loading a workflow from
  Nuke closes the one Nuke loaded before and leaves other open workflows alone. Runs in other
  workflows no longer reach Nuke. Requires engine 0.111.0 or later.
  [#204](https://github.com/griptape-ai/griptape-nodes-library-nuke/issues/204)
