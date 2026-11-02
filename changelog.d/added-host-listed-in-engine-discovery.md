- A connected Nuke host is listed on the engine's session under its `client_name`, so engine
  discovery (`GET /api/engines` and the engine heartbeat) shows which engine a Nuke session is
  driving. A clean disconnect or a forced takeover delists the previous host. Needs engine 0.105.0.
  [#163](https://github.com/griptape-ai/griptape-nodes-library-nuke/pull/163)
