- Nuke keeps working while the engine has other workflows open, such as editor tabs, instead of
  failing with `WorkflowNotNamedError`. Loading a workflow from Nuke replaces the one Nuke loaded
  before and leaves other open workflows alone. With nothing loaded from Nuke, Nuke drives the one
  workflow open in the editor itself, so it still does on engines that no longer pick that
  workflow for a request that names none.
  [#204](https://github.com/griptape-ai/griptape-nodes-library-nuke/issues/204)
