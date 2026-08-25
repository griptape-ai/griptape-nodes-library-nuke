# Nuke Host API

A versioned API for driving the Griptape Nodes engine from Foundry Nuke.

Nuke is pinned by studios for years and its plugin is a recompiled-per-version C++
binary, so it is the slowest-moving artifact in the system. The engine ships weekly.
This library sits between them: it owns a small set of verbs and value types that the
plugin binds to, and absorbs engine churn behind them.

```
griptape-nodes-library.json       library registration
nuke_nodes/
  nuke_library_advanced.py         registers verbs, installs/tears down the event bridge
  nuke_api_info.py                 NukeApiInfo, a canvas-visible diagnostics node
nuke_host_api/
  protocol.py                      THE FROZEN SURFACE. versions, verbs, host types
  events.py                        request/result/notification payloads
  handlers.py                      host verb in, engine request out
  execution_bridge.py              engine execution events -> host notifications
  value_types.py                   value normalizer
tests/unit/
  test_protocol.py                 verb/notification names resolve to real payload classes
  test_value_types.py              value mapping table and descriptor shape
  test_macros.py                   macro resolution, patterns, unresolved tokens
  test_handlers.py                 shape parsing, port narrowing, negotiation
  test_execution_bridge.py         subscription symmetry, event translation
```

`protocol.py` is the file to read first and the file to change most carefully. It is
the only place a name the plugin knows may be introduced or retired.

## Run it

Unit tests need nothing running:

```bash
make test/unit
```

There is no reference client in the repo. `INTEGRATION.md` is the contract; a host is
verified against a running engine by hand until the plugin exists.

## The four capabilities

### 1. Connect

`NukeConnectRequest` negotiates a protocol version and returns the engine version, the
closed host type set, and the event topic. Offering an unsupported version gets a clean
refusal naming the support window.

Finding an engine to connect to happens off the wire, because a host has no connection yet:
`engines.json` lists engines and a per-engine socket path doubles as the liveness check. See
`INTEGRATION.md`.

### 2. Execute workflows

`NukeListWorkflowsRequest` (with `runnable_only`) and `NukeDescribeWorkflowRequest` for
discovery, then `NukeExecuteWorkflowRequest`, with `NukeGetExecutionStateRequest` and
`NukeCancelExecutionRequest` against the engine.

No execution identifier, deliberately. The engine threads none through its execution events, so
any id minted here could not be correlated with the notifications that follow; attributing
events to "whatever started most recently" is silently wrong as soon as anything else
drives the engine, including the editor. Adding an id once the engine carries one is an
additive change and costs no version bump, so there is no reason to fake one now.

What makes that survivable is refusing to start a second run while one is in progress.
Without the guard, a host could load a graph over a running one and then be unable to tell
which run any following notification described, or which one a cancel would stop.

One host verb, three engine requests. The engine has no execute-with-inputs entry point:
`RunWorkflowFromRegistryRequest` loads the graph, `SetParameterValueRequest` applies
each input to the loaded start node, and `StartFlowRequest` executes. A host should not
have to know that sequence, or that it may change.

`NukeExecuteWorkflowResultSuccess` reports `applied_inputs` and `rejected_inputs`, because a
silently dropped input is worse than a failed execution: the workflow produces plausible
output from the wrong values. Inputs are checked against the ports `describe_workflow`
declared before they reach the engine, which would otherwise set a parameter on any node in
the loaded graph for a caller this transport never authenticated.

`NukeDescribeWorkflowRequest` carries each port's `default`, `tooltip`, and `settable`
alongside its type, because a host builds knobs from this and a knob with no default has
nothing to initialize to. The default is a value descriptor, so a port's default and its
live value are one shape.

### 3. Node execution changes

Eight engine execution events collapse into four states (`unresolved`, `running`,
`resolved`, `failed`) delivered as `NukeNodeStateEvent`. The ratio is the point: the
engine can add a ninth event type without the host learning anything.

### 4. Parameter value changes

`NukeParameterValueEvent` carries a **normalized descriptor**, not a raw engine value.
The same normalizer that types ports in `describe_workflow` shapes every live update, so
a host has one value format rather than two.

### Push, with a recovery path

Notifications are real pushes, not polling: the bridge subscribes in-process, translates,
and `put_event(AppEvent(...))` reaches every connected socket. Three limits shape how a
plugin must use it.

- **Fire and forget.** The Rust fan-out drops send errors on the floor. No acks, no
  backpressure, no delivery guarantee.
- **No replay.** There is no buffer or backlog, so a plugin that connects mid-execution or drops
  its socket has permanently missed those events.
- **No filtering.** On `local_socket` every outbound frame reaches every client, so a
  plugin that does not filter will process the editor's replies as its own. There is no
  subscription step to forget, which is the one failure mode this transport removes.

`NukeGetExecutionStateRequest` is therefore the recovery path for running state and output
values: it reads flow state and the declared output values straight from the engine, so a
reconnecting host that missed everything can still get current truth about what is
running and what a workflow's output ports currently hold. It holds no cache, which is why
it cannot drift. It is **not** a recovery path for a run's outcome: the engine exposes no
flow-level success/failure field anywhere, on this request or any other, so a host that
misses the live `NukeNodeStateEvent` with `state: "failed"` has no way to learn afterward
that a run failed.

**Outputs have exactly one meaning:** the ports `NukeDescribeWorkflowRequest` declared.
The engine's terminal event reports values for whichever node control flow ended on, which
is often not a declared output node, so `NukeExecutionStateEvent` carries only
`terminal_node` and never outputs. Reading values in that callback would also violate the
engine's instruction that execution event listeners stay cheap and non-blocking.

## Value contract

Closed set, seven members: `GTImage`, `GTMovie`, `GTFile`, `GTText`, `GTNumber`,
`GTBool`, `GTNull`.

```json
{"value_type": "GTImage",
 "sources": [{"kind": "url|path|inline|macro", "value": "...", "format": "exr",
              "width": null, "height": null, "byte_count": null,
              "is_pattern": true, "raw": "{outputs}/render.{###}.exr"}],
 "colorspace": null,
 "engine_type": "ImageUrlArtifact"}
```

The engine expresses "an image" in at least six shapes, and the artifact vocabulary
belongs to the griptape SDK (16 classes on a third release cadence). Some types the Nuke
library already consumes are not in the SDK at all: `ThreeDUrlArtifact`,
`GLTFUrlArtifact`, and `ImageSequenceArtifact`, the last being really
`ListArtifact[ImageUrlArtifact]`. `ImageUrlArtifact`, `VideoUrlArtifact`,
`BlobArtifact`, and `GenericArtifact` are structurally identical, all carrying a single
`value`, so the class name is the only discriminator.

14 representative shapes, all landing in the seven-member set:

```
GTImage    <- ImageUrlArtifact, static server URL          [url/png]
GTImage    <- ImageUrlArtifact, remote URL no extension    [url/?]
GTImage    <- ImageArtifact, inline bytes                  [inline/png]
GTImage    <- "Sequence" or list[ImageUrlArtifact] port    [many sources]
GTMovie    <- VideoUrlArtifact                             [url/mov]
GTImage    <- bare string, absolute path                   [path/exr]
GTText     <- bare string, prose                           [no sources]
GTImage    <- ListArtifact of images                       [url/exr, url/exr, url/exr]
GTFile     <- BlobArtifact                                 [inline/?]
GTImage    <- GenericArtifact wrapping a jpg URL           [url/jpg]
GTImage    <- macro, project outputs dir                   [path/png]
GTImage    <- macro with sequence slot                     [path/exr/pattern]
GTImage    <- macro with unbound directory                 [macro/png]
GTImage    <- unresolved workflow variable                 [macro/exr]
```

Rules:

- **Moves no bytes.** No downloads, no copies, no header sniffing. The engine writes
  wherever it writes; this layer makes the shape predictable.
- **Does perform pure resolution.** Project macros resolve through
  `GetPathForMacroRequest`, which has no disk writes.
- **Never guesses a format.** Unknown is `null`.
- **`kind` is explicit**, so a host never sniffs whether a string is a URL, path, macro,
  or prose.
- **A declared port type outranks the extension**, except for an artifact class this version
  does not map: there the extension is the only media information there is, so an unmapped
  class describes as `GTFile` and its values may narrow to `GTImage` or `GTMovie`. Narrowing
  never leaves the sourced types.
- **Sequences are source count, not a host type**, so sequence support costs no version bump.
- **`engine_type` is diagnostic only** and must never be branched on.

## Versioning

`PROTOCOL_VERSION` is one integer, bumped only by a breaking change.

Free: adding a field, mapping a new engine artifact class onto an existing host type,
adding a verb or notification type. **Verified**: an unknown request field is ignored, so
additive change safety is real rather than aspirational.

Bumps: removing or renaming a verb, event, field, host type, or source kind, or changing
the meaning of one.

`SUPPORTED_PROTOCOL_VERSIONS` is the support window. Studios keep plugin binaries in
service for years, so entries leave on a stated schedule.

### Nothing protects the contract yet

The surface is not frozen. No plugin binary has been compiled against it, so there is no
promise to keep and the set of verbs, types, and fields is still being reshaped.

A snapshot guard belongs here the day the first plugin ships. It records everything a
plugin can observe (verb and notification names, every payload's fields and whether each
is required, the value type and source kind sets, the state strings, the descriptor keys)
and asserts **frozen remains a subset of current**, which is the versioning policy made
executable:

| Change | Result |
|---|---|
| Add a verb, notification, field, value type | passes, no version bump |
| Remove or rename any of them | **fails** |
| Make an optional field required | **fails** |
| Drop a version from the support window | **fails** |

A working implementation is archived at
`~/archive/griptape-nodes-library-nuke/host-api-reference-clients-20260825/`, along with
the steps to restore it. Recording a version is a promise to plugins already compiled
against it, so record once and never overwrite.

Until then, the rest of the suite does not catch a rename. Renaming a verb and deleting a
result field, with the rename propagated into the tests the way an IDE would, leaves all
other tests green.

### What is still not covered

Being explicit, because these are the remaining ways the contract can break.

- **Semantic drift.** Nothing detects a field that keeps its name and changes meaning. If
  `terminal_node` started reporting the declared output node instead of the node control
  flow ended on, every test passes and plugin behaviour silently changes.
- **Engine semantic drift.** Shape drift is caught, because the unit tests construct real
  engine payloads like `ControlFlowResolvedEvent(end_node_name=...)` and fail if a field is
  renamed. Meaning changes are not.
- **Host-side tolerance.** Additive safety is verified inbound: an unknown request field is
  ignored. The outbound direction depends on the plugin's JSON parser ignoring unknown
  result fields, which cannot be tested from here and must be a plugin review requirement.
- **No replayed wire frames.** The snapshot pins names and shapes, not a recorded byte
  stream deserialized through `EventRequest.from_dict`. That would additionally catch
  serialization-level regressions in the engine's own event plumbing.
- **The support window is a list, not a policy.** Dropping v1 fails the test, but nothing
  encodes how long a version must stay supported. That remains a human decision.

## Constraints discovered while building this

Load-bearing for the design, and documented nowhere obvious.

1. **Library-internal top-level packages are process-global.** The first library to
    import a given package name owns it for the process lifetime; a later copy silently
    runs the first copy's code. Hence the distinctive `nuke_host_api` name. Two protocol
    versions therefore **cannot** ship as sibling libraries sharing an internal package.
    If the support window ever needs two live implementations they must be separate
    modules inside one library.

2. **`get_request_handlers()` is singleton per request type engine-wide.** Exactly one
    library may own each verb, so two copies of this package cannot both load. It is also
    **orchestrator-process only**: a worker-mode library's handlers are not forwarded and
    requests fail with "No manager found".

3. **Execution event listeners are not cleaned up for you.** The engine deregisters
    request handlers on unload but not execution event listeners. Without
    `before_library_unregistered` calling `ExecutionBridge.uninstall()`, a reload leaves
    the old bridge subscribed and a host receives every notification twice, then three
    times. Observed directly: notification counts were an exact 3x multiple of a
    single-bridge run with three copies loaded. After wiring teardown, counts are stable
    across repeated runs.

4. **`broadcast_app_event` does not reach a host.** It only notifies in-process
    listeners. `put_event(AppEvent(payload=...))` is the path that reaches IPC.

5. **Result shapes are not stable in type, only in key.** `workflow_shape` arrives as a
    JSON string for some workflows and null for others. An early version assumed a dict
    and silently returned zero ports for every workflow while every request still
    reported success.

6. **A library with zero nodes fails to load** with "no nodes were loaded". Not an issue
    here, since this library already ships nodes.

7. **FAILURE state is sticky by library name** and `UnloadLibraryFromRegistryRequest`
    does not clear it, so a library that failed to register once needs an engine restart
    before it can be registered again.

8. **The engine cannot express colorimetry.** It reports `color_space`
    (`image_artifact_provider.py:37`), but the values come from a PIL mode map: `RGB`,
    `RGBA`, `Grayscale`, `CMYK`. That is channel layout, not a transfer function, so
    nothing can say whether pixels are sRGB or scene-linear. Nuke works scene-linear, so
    untagged 8-bit output is silently wrong and reads as a tool bug.
    `GTImage.colorspace` is reserved and always null: a nullable field now is free, a
    required one later is a version bump.

9. **Two brace systems share one syntax.** Directory macros (`{outputs}`) and workflow
    variables (`{MY_VAR}`) are syntactically identical, and only name resolution separates
    them. Substitution normally runs during `aprocess()` but can be disabled per-parameter
    or engine-wide, so a `"{" in value` test cannot tell a resolvable path from a leftover
    variable. Unresolvable tokens are reported as `kind="macro"` with `raw` preserved.

10. **Nuke inverts the engine's own warning about sequence patterns.**
    `RENDER_SEQUENCE_PATTERN` is documented as presentation-only, "NOT a valid filesystem
    path ... must not be opened". For a Nuke Read node that form is the *operationally
    correct* one, since Nuke expands the padding itself. Both are true, so the descriptor
    carries `is_pattern`: safe for a Read knob, not for `open()`. The alternatives were
    both wrong for Nuke, since `FAIL` rejects every sequence and resolving to one frame
    loses the range.

## Known gaps

- **Audio lands in `GTFile`.** v1 covers images and movies. Promoting it to `GTAudio` is a
  version bump, so decide deliberately rather than by omission.
- **No execution identity.** The engine carries no execution id through its
  execution events, so nothing here can correlate concurrent executions. This layer
  deliberately does not paper over it with local state; the fix belongs in the engine.
  Serial execution is enforced instead: a second `NukeExecuteWorkflowRequest` is refused
  while a run is in progress.
- **`NukeCancelExecutionRequest` cancels whatever is running**, because the engine offers
  no way to name a specific execution. Correct while executions are serial, wrong the
  moment they are not. This is the concrete cost of the missing engine-side execution id.
- **Registry entries can be stale.** `NukeListWorkflowsRequest` checks that a workflow's
  file still exists, because the registry keeps entries for deleted files and its own
  `is_saved` flag stays true for them.
- **Port metadata stops at `default`, `tooltip`, and `settable`.** The engine also carries
  `ui_options`, holding slider ranges (`range_slider`, `step`), dropdown choices
  (`simple_dropdown`, `multi_options`), and `multiline`. Passing that dict through raw would
  hand a plugin author editor vocabulary to bind to, so whatever a Nuke knob needs from it
  should be narrowed into named fields first. Adding them costs no version bump.
- **A host addresses inputs by node name.** Node names are editable in the canvas, so
  renaming a start node breaks a host's saved knob mapping. Re-describing on connect is the
  only mitigation today.
- **A stuck node locks a host out.** `_flow_is_running` is true while the engine reports any
  resolving or control node, and execute refuses while it is. A node that never returns, a
  Nuke subprocess that hangs, leaves that state set and every later execute refused. The
  escape is `NukeCancelExecutionRequest`, and whether cancel actually clears a node wedged
  inside `process()` is unverified. If it does not, only an engine restart recovers.
- **`local_socket` ships disabled.** Every machine needs a config edit before a plugin can
  reach an engine. Worth an engine-side default.
