# Nuke Host API

A versioned API for driving the Griptape Nodes engine from Foundry Nuke.

Nuke is pinned by studios for years and its plugin is a recompiled-per-version C++
binary, so it is the slowest-moving artifact in the system. The engine ships weekly.
This library sits between them: it owns a small set of verbs and value types that the
plugin binds to, and absorbs engine churn behind them.

```
griptape-nodes-library.json       library registration
nuke_nodes/
  nuke_library_advanced.py         registers verbs, tears down the event bridge on unload
nuke_host_api/
  protocol.py                      THE FROZEN SURFACE. versions, verbs, host types
  events.py                        request/result/notification payloads
  handlers/                        host verb in, engine request out
    __init__.py                      ROUTES: the only verb -> handler binding
    connect.py                       version negotiation, event stream opening
    workflows.py                     list, describe
    load.py                          load one workflow, describe and read it back
    execution.py                     execute, state, cancel
    values.py                        bulk parameter-value reads, selectable by side
  engine.py                        engine request narrowing and shared queries
  shape.py                         workflow_shape -> host-visible parameters
  parameter_values.py              reading a loaded workflow's values, shared by load and values
  dispatch.py                      handler calling convention: request guard, failure wording
  library_version.py               the shipped version, read from the manifest
  execution_bridge.py              engine execution events -> host notifications
  value_types.py                   value normalizer
tests/unit/
  test_protocol.py                 verb/notification names resolve to real payload classes
  test_value_types.py              value mapping table and descriptor shape
  test_macros.py                   macro resolution, patterns, unresolved tokens
  test_shape.py                    shape parsing, parameter narrowing, runnability
  test_engine.py                   narrowing, event topic, shared queries
  test_parameter_values.py         section reading, unavailable reporting, control exclusion
  test_dispatch.py                 request guard, failure wording
  test_library_version.py          manifest read and reload reset
  test_handlers_routes.py          every declared verb is routed exactly once
  test_handlers_connect.py         negotiation, event stream gating
  test_handlers_workflows.py       discovery and parameter publication
  test_handlers_load.py            argument checks, load ordering, read-back
  test_handlers_execution.py       run guards, input allow-list, state, cancel
  test_handlers_values.py          section selection, unavailable reporting, normalization
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

## The capabilities

### 1. Connect

`NukeConnectRequest` negotiates a protocol version and returns the engine version, the
closed host type set, and the event topic. Offering an unsupported version gets a clean
refusal naming the support window.

Finding an engine to connect to happens off the wire, because a host has no connection yet:
a host holds the `websocket_direct` URL as its own setting, defaulted to
`ws://127.0.0.1:18125/`, and a completed handshake is the liveness check. The engine's
`engines.json` is app-layer internal and deliberately not part of what a host reads. See
`INTEGRATION.md`.

### 2. Load a workflow

Two kinds of verb, and which kind a host is holding decides what it must know.

| Addressed by | Verbs | Answers with |
|---|---|---|
| `workflow_id`, from the registry | `NukeListWorkflowsRequest`, `NukeDescribeWorkflowRequest` | what a workflow declares, loaded or not |
| the engine's loaded graph | `NukeGetParameterValuesRequest`, `NukeGetExecutionStateRequest`, `NukeCancelExecutionRequest`, `NukeExecuteWorkflowRequest` | what the engine currently holds |

`NukeLoadWorkflowRequest` is the only verb that moves a workflow from the first row to the
second, and the only one that changes what is loaded.

The split is not decorative. A parameter's live value exists on a loaded node, so a verb
reading one cannot take a `workflow_id` and mean it: for an unloaded workflow there is nothing
to read, and the only way to make one readable is to load it, which clears all object state.
A read verb that quietly did that would discard a graph an editor user had open. So loading is
its own verb, called deliberately, and a host is expected to confirm it with the artist.

Before it existed, loading was a side effect of `NukeExecuteWorkflowRequest`, which left a
host unable to read or set a parameter's live value without starting a run.

One host verb, four engine requests plus one per declared parameter, because the engine has no
load-and-describe entry point: `ImportWorkflowRequest` registers a file the engine has not seen
and costs one more, `RunWorkflowFromRegistryRequest` builds the graph, and values come back one
`GetParameterValueRequest` at a time.

The reply carries four fields rather than two: `inputs` and `outputs` are exactly
`describe_workflow`'s parameter lists, and `input_values` and `output_values` are exactly
`NukeGetParameterValuesRequest`'s maps. No new shape, and no field with two meanings. A
parameter's declaration and its current value have different lifetimes, so folding a value
into a descriptor would make `default` and `value` look like variants of one thing.

`workflow_id` or `file_path`, never both, since they can name different workflows and guessing
is worse than refusing. A `file_path` is imported and registered first, so a host can hand
over a file an artist picked and learn the resulting id from the reply.

Every check this verb makes itself happens before the engine is touched, including reading the
registry to reject an unknown id, so a request refused on its own arguments leaves the previous
graph intact. The engine's own load is not atomic and cannot offer that: `run_with_clean_slate`
clears all object state before the graph is built, so a workflow that fails inside its own file
leaves nothing loaded. That failure reports `engine_state_cleared`, and a host must drop the
knobs it was showing when it sees it.

### 3. Execute workflows

`NukeListWorkflowsRequest` (with `runnable_only`) and `NukeDescribeWorkflowRequest` for
discovery, `NukeLoadWorkflowRequest` to put one in the engine, then
`NukeExecuteWorkflowRequest`, with `NukeGetExecutionStateRequest` and
`NukeCancelExecutionRequest` against the engine.

No execution identifier, deliberately. The engine threads none through its execution events, so
any id minted here could not be correlated with the notifications that follow; attributing
events to "whatever started most recently" is silently wrong as soon as anything else
drives the engine, including the editor. Adding an id once the engine carries one is an
additive change and costs no version bump, so there is no reason to fake one now.

What makes that survivable is refusing to start a second run while one is in progress.
Without the guard, a host could not tell which run any following notification described, or
which one a cancel would stop. `NukeLoadWorkflowRequest` refuses mid-run for the same reason
and a stronger one: it would discard the running graph.

Six engine requests plus one per input forwarded to the engine, and none of them loads.
`SetParameterValueRequest` applies each declared input to the loaded start node and
`StartFlowRequest` executes, so running a workflow does not rebuild the graph whose knobs a host
has just been setting. The rest is preflight: what the engine is running, what it has loaded,
what that workflow declares, and which flow to start.

A pair outside the allow-list is the only rejection that costs nothing, because it never reaches
the engine. A declared pair is forwarded before its outcome is known, so an input the engine
refuses has already cost its request.

`workflow_id` is optional. Empty runs whatever is loaded, which is what a host driving a graph
an editor user opened has to do. Set, it must be the loaded workflow, and a mismatch is
refused: honouring it would put loading back inside execute, and ignoring it would run a
workflow the host did not ask for while reporting success. A host that tracks what it loaded
should send it, because that turns a graph swapped out from under it into a refusal.

`NukeExecuteWorkflowResultSuccess` reports `applied_inputs` and `rejected_inputs`, because a
silently dropped input is worse than a failed execution: the workflow produces plausible
output from the wrong values. Inputs are checked against the parameters `describe_workflow`
declared before they reach the engine, which would otherwise set a parameter on any node in
the loaded graph for a caller this transport never authenticated.

By the same rule, inputs sent to a loaded graph that declares no input parameters are refused
rather than rejected one by one. `workflow_id` empty is how a host drives a graph it did not
load, and the engine keeps the unsaved graph an editor user is working on in its registry
under an `unsaved:` key with no declared shape. Rejecting each input there would report the
host's own parameter names back at it as if they were wrong, while the run went ahead on the
author's values.

An unreadable registry, and an id that has vanished from a readable one, leave the same empty
allow-list for unrelated reasons, and each gets a refusal of its own: retry the registry, or
load the workflow again. A workflow that declares nothing will still declare nothing on the
next call; the other two are not the host's doing. Telling a host to save a workflow it already
saved sends it down the wrong recovery path. None of the three fires when no inputs were sent,
because then there is nothing to check against the allow-list.

`NukeDescribeWorkflowRequest` carries each parameter's `default`, `tooltip`, and `settable`
alongside its type, because a host builds knobs from this and a knob with no default has
nothing to initialize to. The default is a value descriptor, so a parameter's default and its
live value are one shape.

### 4. Read every declared parameter value

`NukeGetExecutionStateRequest` answers exactly one question: is the engine running, and
which nodes are involved. `NukeGetParameterValuesRequest` answers a different one: what does
every declared start-flow or end-flow parameter currently hold. Each verb has one meaning,
and a host reads every input-side parameter as readily as every output-side one.

`sections` selects `"inputs"`, `"outputs"`, or both (the default, when the list is empty),
so a host reads a start node's parameters, an end node's parameters, or everything in one
call instead of one `GetParameterValueRequest` per parameter. `requested_sections` echoes what
was actually read, so a host can tell a section it did not ask for from a section that came
back empty. `unavailable` reports, rather than silently omits, any declared parameter the engine
would not answer for, because an absent entry and an empty one mean different things when
a host is deciding what to show on a knob.

Answered by one engine request per declared parameter rather than the engine's own
`GetAllNodeInfoRequest`, which batches a node's info into one call but keys its parameter
values by internal element id, hands artifacts back display-serialized into plain dicts
rather than the instances the normalizer inspects, and drops any parameter whose value is
`None`. See `parameter_values.py` for the full comparison.

The reading itself lives in `parameter_values.py`, shared with `NukeLoadWorkflowRequest`, so
the values a host is handed at load and the values it reads back later cannot disagree, and
neither can how an unreadable parameter is reported.

### 5. Node execution changes

Eight engine execution events collapse into four states (`unresolved`, `running`,
`resolved`, `failed`) delivered as `NukeNodeStateEvent`. The ratio is the point: the
engine can add a ninth event type without the host learning anything.

### 6. Parameter value changes

`NukeParameterValueEvent` carries a **normalized descriptor**, not a raw engine value.
The same normalizer that types parameters in `describe_workflow` shapes every live update, so
a host has one value format rather than two.

### Push, with a recovery path

Notifications are real pushes, not polling: the bridge subscribes in-process, translates,
and `put_event(AppEvent(...))` reaches every connected socket. Three limits shape how a
plugin must use it.

- **Fire and forget.** The Rust fan-out drops send errors on the floor. No acks, no
  backpressure, no delivery guarantee.
- **No replay.** There is no buffer or backlog, so a plugin that connects mid-execution or drops
  its connection has permanently missed those events.
- **Topic routing is not filtering.** `event_topic` is the engine's default response topic,
  shared with the editor and every other library, so a plugin filters on `request_id` and
  `payload_type` as well as subscribing. Replies are isolated: a host picks its own
  `response_topic` and only its subscribers see those.
- **Notifications begin at connect.** The bridge installs on the first `NukeConnectRequest`,
  not at library load, so an engine no host has spoken to pays nothing for a feed nobody
  reads. A host that skips connect gets replies and no events.

The transport a plugin uses is `websocket_direct`, not `local_socket`, and the slow-reader
hazard is why. `local_socket` writes to every client serially under one lock, so a client
that stops reading long enough to fill its socket buffer is dropped from the broadcast set
on the first write error and receives nothing further, replies included, while its read side
stays open. Observed while running the smoke tests: a single-threaded client that paused
between requests hit a 60 second reply timeout on a healthy socket, and a wedged client also
delays delivery to the editor. `websocket_direct` gives each connection its own unbounded
queue and writer task, so a slow reader costs engine memory instead of frames and stalls
nobody. A plugin still reads on a dedicated thread that never blocks.

`NukeGetExecutionStateRequest` and `NukeGetParameterValuesRequest` together are the recovery
path: a reconnecting host that missed every notification reads what is running from the
first and what every declared parameter currently holds from the second. Both read straight from
the engine on every call, holding no cache, which is why neither can drift from the
engine's own view. Neither is a recovery path for a run's outcome: the engine exposes no
flow-level success/failure field anywhere, on either request or any other, so a host that
misses the live `NukeNodeStateEvent` with `state: "failed"` has no way to learn afterward
that a run failed.

**Outputs have exactly one meaning:** the parameters `NukeDescribeWorkflowRequest` declared.
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
GTImage    <- "Sequence" or list[ImageUrlArtifact]         [many sources]
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
- **A declared parameter type outranks the extension**, except for an artifact class this version
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
    `before_library_unregistered` calling `execution_bridge.uninstall()`, a reload leaves
    the old bridge subscribed and a host receives every notification twice, then three
    times. Observed directly: notification counts were an exact 3x multiple of a
    single-bridge run with three copies loaded. After wiring teardown, counts are stable
    across repeated runs.

    The subscription is also engine-global: listeners are keyed by event type, not by
    library or node, so an installed bridge translates and re-emits for every workflow the
    engine runs, including ones with no Nuke nodes driven from the editor. Hence installing
    on first connect rather than at load. Latching on without ever counting back down is
    deliberate, because the transport gives Python no disconnect signal; an idle timeout
    would tear the feed down exactly when a host sits quietly waiting on a long render.

4. **`broadcast_app_event` does not reach a host.** It only notifies in-process
    listeners. `put_event(AppEvent(payload=...))` is the path that reaches IPC.

5. **Result shapes are not stable in type, only in key.** `workflow_shape` arrives as a
    JSON string for some workflows and null for others. An early version assumed a dict
    and silently returned zero parameters for every workflow while every request still
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
- **Parameter metadata stops at `default`, `tooltip`, and `settable`.** The engine also carries
  `ui_options`, holding slider ranges (`range_slider`, `step`), dropdown choices
  (`simple_dropdown`, `multi_options`), and `multiline`. Passing that dict through raw would
  hand a plugin author editor vocabulary to bind to, so whatever a Nuke knob needs from it
  should be narrowed into named fields first. Adding them costs no version bump.
- **A host addresses inputs by node name.** Node names are editable in the canvas, so
  renaming a start node breaks a host's saved knob mapping. Re-describing on connect is the
  only mitigation today.
- **A stuck node locks a host out.** `flow_is_running` is true while the engine reports any
  resolving or control node, and both execute and load refuse while it is. A node that never
  returns, a Nuke subprocess that hangs, leaves that state set and every later execute and load
  refused. The escape is `NukeCancelExecutionRequest`, and whether cancel actually clears a node
  wedged inside `process()` is unverified. If it does not, only an engine restart recovers.
- **Loading is destructive and nothing but a host's own UI guards it.**
  `NukeLoadWorkflowRequest` clears all object state, which discards whatever the engine held,
  including a graph an editor user has open on the same engine. The engine offers no
  load-into-a-side-context entry point, so this layer cannot make it non-destructive. A host
  should confirm with the artist before sending it.
- **A host cannot set a value without running.** Inputs are applied by
  `NukeExecuteWorkflowRequest` and nothing else, so a host that wants to stay live with the
  engine as an artist edits a knob has no verb for it. A bulk `NukeSetParameterValuesRequest`
  is the missing half of `NukeGetParameterValuesRequest`.
- **`websocket_direct` ships disabled.** Every machine needs a config edit before a plugin can
  reach an engine. Worth an engine-side default.
- **`NukeGetParameterValuesRequest` and `NukeLoadWorkflowRequest` cost one engine request per
  declared parameter, with no transport-level batching in this layer.** A workflow's declared
  surface is knobs, not hundreds of them, so the cost has not mattered in practice. If it ever
  does, the fix is the engine's own `EventRequestBatch` wire envelope (`INTEGRATION.md`, Frame
  formats), which packs many host verb frames into one WebSocket message; it is a transport
  optimization a host applies itself, not something a handler can opt into on a host's behalf.
