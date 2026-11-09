- `NukePingRequest` lets a Nuke host check that the engine itself is alive. The transport's `ping`
  frame only proves the connection is up, and over the hosted connection it keeps answering after
  the engine stops.
