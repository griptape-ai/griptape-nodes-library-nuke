- A published gizmo on engine 0.105.0 handed Nuke the literal `{outputs}/...` macro for an artifact
  output instead of the file's path. The gizmo runner now resolves path macros itself when it
  hands outputs to Nuke, and Nuke End Flow stores outputs exactly as the engine hands them, so a
  published workflow no longer carries absolute paths from the author's machine.
  [#182](https://github.com/griptape-ai/griptape-nodes-library-nuke/pull/182)
