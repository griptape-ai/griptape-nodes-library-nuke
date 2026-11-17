- Nuke keeps working while the engine has other workflows open, such as editor tabs, instead of
  failing with `WorkflowNotNamedError`. Loading a workflow from Nuke replaces the one Nuke loaded
  before and leaves other open workflows alone.
  [#204](https://github.com/griptape-ai/griptape-nodes-library-nuke/issues/204)
