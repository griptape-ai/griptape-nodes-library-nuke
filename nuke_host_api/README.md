# Nuke Host API

A versioned API for driving the Griptape Nodes engine from Foundry Nuke.

Studios pin Nuke and rebuild its C++ plugins per version, while the engine releases independently. This library gives the plugin a small, stable set of verbs and value types and absorbs engine changes.

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
    values.py                        bulk parameter-value reads and writes, addressed to the loaded workflow
    projects.py                      list, current, switch, describe a project
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
  test_handlers_values.py          section selection, unavailable reporting, normalization, set-value allow-list
  test_handlers_projects.py        project narrowing, running-engine refusal, workspace-change detection
  test_execution_bridge.py         subscription symmetry, event translation
```

`protocol.py` is the file to read first and the file to change most carefully. It is
the only place a name the plugin knows may be introduced or retired.

## Run it

Unit tests need nothing running:

```bash
make test/unit
```

The live smoke suite drives a running engine through the stdlib harness in
`tests/integration/host_api_client.py`:

```bash
make test/integration/host-api
```

It uses `local_socket` rather than the plugin transport, `websocket_direct`.
`INTEGRATION.md` defines transport behavior not covered by the smoke suite.

`scripts/nuke_host_panel/` covers the rest by hand: a host in a browser, over
`websocket_direct`, shaped like a host rather than a list of requests with buttons on them. It
connects itself and reconnects, reads the project before the workflow list, describes before it
loads, writes parameter edits through coalesced, locks during a run, draws progress from the run's
node set, shows each output with the `nuke.nodes` call it would become, and keeps the runs it has
seen. Every verb and notification is reached by that flow; the wire log and event feed are in a
drawer. It is a testing dashboard, not a second reference client, so no part of its shape is a
contract.

```bash
make host-api/dashboard
```

Enable `websocket_direct` first (`INTEGRATION.md`, "Connecting"). The page fetches Preact and
htm from a CDN on first load and says so rather than rendering blank when it cannot.

## The capabilities

### 1. Connect

`NukeConnectRequest` negotiates a protocol version and returns the engine version, the
closed host type set, and the event topic. Offering an unsupported version gets a clean
refusal naming the support window.

`NukeConnectResultSuccess` also carries `engine_id`, `session_id`, and `engine_name`, read from
the versioned handshake reply rather than the result envelope (see `INTEGRATION.md`).
`session_id` is the engine's active session, shared engine state rather than this
connection's own; all three are empty string, never null, when the engine has none to
report, and a connect that cannot name the engine is still a successful handshake.

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
| the engine's loaded graph | `NukeGetParameterValuesRequest`, `NukeSetParameterValuesRequest`, `NukeGetExecutionStateRequest`, `NukeCancelExecutionRequest`, `NukeExecuteWorkflowRequest` | what the engine currently holds |

`NukeLoadWorkflowRequest` is the only verb that moves a workflow from the first row to the
second, and the only one that changes what is loaded.

A parameter's live value exists on a loaded node, so a verb reading one cannot take a
`workflow_id` and mean it: for an unloaded workflow there is nothing
to read, and the only way to make one readable is to load it, which clears all object state.
A read verb that quietly did that would discard a graph an editor user had open. So loading is
its own verb, called deliberately, and a host is expected to confirm it with the artist.

The engine has no load-and-describe entry point. Loading uses four engine requests plus one per declared parameter: `ImportWorkflowRequest` registers an unseen file, `RunWorkflowFromRegistryRequest` builds the graph, and values require one `GetParameterValueRequest` each.

The reply carries four fields rather than two: `inputs` and `outputs` are exactly
`describe_workflow`'s parameter lists, and `input_values` and `output_values` are exactly
`NukeGetParameterValuesRequest`'s maps. No new shape, and no field with two meanings. A
parameter's declaration and its current value have different lifetimes, so folding a value
into a descriptor would make `default` and `value` look like variants of one thing.

`workflow_id` or `file_path`, never both, since they can name different workflows and guessing
is worse than refusing. A `file_path` is imported and registered first, so a host can hand
over a file an artist picked and learn the resulting id from the reply.

Every check this verb makes itself happens before the engine is touched, including reading the
registry to reject an unknown id, so a request refused on its own arguments leaves the loaded
graph intact. A `file_path` is imported and registered before those checks run, so a refusal
there can leave a registry entry behind, never a different graph. The engine's own load is not
atomic and cannot offer even that much: `run_with_clean_slate` clears all object state before
the graph is built, so a workflow that fails inside its own file leaves nothing loaded. That
failure reports `engine_state_cleared`, and a host must drop the knobs it was showing when it
sees it.

### 3. Execute workflows

`NukeListWorkflowsRequest` (with `runnable_only`) and `NukeDescribeWorkflowRequest` for
discovery, `NukeLoadWorkflowRequest` to put one in the engine, then
`NukeExecuteWorkflowRequest`, with `NukeGetExecutionStateRequest` and
`NukeCancelExecutionRequest` against the engine.

No execution identifier. The engine threads none through its execution events, so
any id minted here could not be correlated with the notifications that follow; attributing
events to "whatever started most recently" is silently wrong as soon as anything else
drives the engine, including the editor. An identifier can be added when engine events carry one.

What makes that survivable is refusing to start a second run while one is in progress.
Without the guard, a host could not tell which run any following notification described, or
which one a cancel would stop. `NukeLoadWorkflowRequest` refuses mid-run for the same reason
and a stronger one: it would discard the running graph.

Six engine requests plus one per input forwarded to the engine, and none of them loads.
`SetParameterValueRequest` applies each declared input to the loaded start node and
`StartFlowRequest` executes, so running a workflow does not rebuild the graph whose knobs a host
has just been setting. The rest is preflight: what the engine is running, what it has loaded,
what that workflow declares, and which flow to start.

Only a forwarded input can be rejected by the engine. A malformed node and a pair outside the
allow-list are both turned away before any request, so they cost nothing; a declared pair is
forwarded before its outcome is known, so an input the engine refuses has already cost its
request.

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

### 4. Read and set declared parameter values

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

`NukeSetParameterValuesRequest` is the write half, for a host that wants to stay live with the
engine as an artist edits a knob rather than only diverging locally until the next
`NukeExecuteWorkflowRequest`. Loaded-state-addressed like the read verb, so it takes no
`workflow_id` either. It takes the same `{node: {parameter: value}}` shape
`NukeExecuteWorkflowRequest.inputs` does, checks it against the same allow-list, built from
`shape.input_parameter_ids`, and reports `applied_inputs`/`rejected_inputs` with the same
wording, so a rejection reads the same way whether a host got it from setting a value live or
from starting a run. `parameter_values.unaddressable_inputs_reason` and
`parameter_values.apply_inputs` are the two functions that make that sharing real rather than
two copies of the same allow-list drifting apart; `handlers/execution.py` and
`handlers/values.py` each supply only their own `attempted` text, failure type, and, if they
have one, the one sentence naming an alternative when their own inputs turn out to be
unaddressable. Execute has one: running the graph as it stands needs no inputs at all.
`NukeSetParameterValuesRequest` does not, and leaves `no_inputs_remedy` unset rather than
naming a remedy this same verb refuses.

A request with no pair to act on and nothing to reject is refused outright, since setting
values is all this verb does: unlike execute, where no inputs still means "run the graph as it
stands," nothing to set is nothing to do. That covers an empty `inputs` and one where every
named node maps to an empty parameter dict, such as `{"Start Flow": {}}`; either would
otherwise reach `apply_inputs` and come back a trivial success indistinguishable from a real
one, with nothing applied and nothing rejected. It is also refused while the engine is
executing, the same guard `NukeLoadWorkflowRequest` and `NukeExecuteWorkflowRequest` apply for
a related reason: the engine's own scheduler decides when a node's parameter is actually read,
so a value set mid-run cannot be told apart from one that lands before the node that consumes
it or one that lands after, and answering as if it landed in time would be a claim this layer
cannot verify. A host that wants to stay live with the engine sets values between runs;
`NukeCancelExecutionRequest` is the way out of a run in progress. Both refusals report the
loaded workflow's id, so a host reading `NukeSetParameterValuesResultFailure.workflow_id` can
tell a busy or empty-request refusal against a loaded graph apart from one where nothing is
loaded at all.

### 5. Node execution changes

Eight engine execution events collapse into four states (`unresolved`, `running`,
`resolved`, `failed`) delivered as `NukeNodeStateEvent`, so the engine can add a ninth event
type without the host learning anything.

`NukeExecutionNodesEvent` forwards the engine's node lists for progress tracking. The first
non-empty list describes the top-level flow. Later lists describe subflows, but contain no
flow identifier. An empty list marks top-level completion.

Lists contain declared nodes, including nodes on untaken branches. A flow whose start is also
its end emits no non-empty list. Events may arrive before `NukeExecuteWorkflowRequest` returns,
so subscribe before executing. If an event is missed while a run is live,
`NukeGetExecutionStateResultSuccess.involved_nodes` provides the top-level list.

### 6. Parameter value changes

`NukeParameterValueEvent` carries a **normalized descriptor**, not a raw engine value.
The same normalizer that types parameters in `describe_workflow` shapes every live update, so
a host has one value format rather than two.

### 7. Projects

Workflows are registered per workspace, and the current project selects the workspace. `NukeListProjectsRequest`, `NukeGetCurrentProjectRequest`, `NukeSetCurrentProjectRequest`, and `NukeDescribeProjectRequest` wrap the engine's project surface (`retained_mode/events/project_events.py`, handled in `retained_mode/managers/project_manager.py`).

`ProjectTemplate` is a pydantic model with dozens of fields, `ProjectValidationInfo` and
`ProjectTemplateInfo` are engine dataclasses, and `ProjectInfo` additionally carries parsed
macro caches. None of them cross the boundary; every field a host reads is a named primitive,
exactly the way `shape.declared_parameters` narrows a parameter dict.
Project ids are opaque the same way workflow ids are: `NukeListProjectsRequest` and
`NukeGetCurrentProjectRequest` hand one back, a host feeds it to
`NukeSetCurrentProjectRequest` or `NukeDescribeProjectRequest`, and it is never parsed or
constructed. `NukeSetCurrentProjectRequest.project_id: None` asks for the system defaults,
mirroring the engine's own `SetCurrentProjectRequest` exactly rather than inventing a
sentinel string a host would have to know about.

`NukeListProjectsRequest` folds the engine's separate `successfully_loaded` and
`failed_to_load` lists into one, the way `NukeListWorkflowsRequest` reports every workflow
with a single `runnable` flag rather than two lists a host must merge itself. It also folds
two unrelated engine mechanisms, a validation failure and an engine-version incompatibility
declared in a project's adjacent config, into one `available` flag and a human-readable
`unavailable_reason`, because a host disabling a menu entry does not need to know which
mechanism fired. `description` is always empty in the list, because the engine's listing
does not carry each template's description, only `NukeDescribeProjectRequest` and
`NukeGetCurrentProjectRequest` read the full template that has one.

`NukeSetCurrentProjectRequest` refuses while the engine is executing, with the same wording
`NukeExecuteWorkflowRequest`'s running-guard uses: reloading libraries out from under a live
run is worse than refusing outright, because the very library driving the run could be torn
down and rebuilt mid-flight.

**A successful switch is a hazard to the host's own connection, always, not only when its
`workspace_changed` field is true.** The engine reloads every library, this one included,
whenever the target project's library-affecting config (which libraries to register or
download, the required engine version, or the resolved libraries directory) differs from
the outgoing project's, and that decision is made independently of whether the workspace
directory changed. `workspace_changed` is computed here by reading the engine's live workspace directory
(`GetWorkspaceRequest`) before and after the switch, not by resolving either project's id
through the same offline previewer `NukeDescribeProjectRequest` uses: that resolver answers
none for any id with no readable project file on disk, which includes the system-defaults
sentinel, so comparing resolved paths around a switch onto or off of system defaults would
report a change whenever none happened. `workspace_changed` answers only "did workflows get
re-registered against a new workspace," never "did libraries reload." A reload tears down this library's request handlers and its outbound
event bridge and rebuilds both (`before_library_unregistered` in
`nuke_nodes/nuke_library_advanced.py`), so a host must send `NukeConnectRequest` again and
re-run `NukeListWorkflowsRequest`/`NukeDescribeWorkflowRequest` after every successful
switch, unconditionally. The reply to the switch itself is unaffected by any of this: the
engine performs the reload synchronously while handling the request, before the reply is
built, so the reply reaches the host regardless. If the target project's workspace does not
configure this library at all, the reload removes this library's verbs entirely, and every
request after that, including the reconnect, fails at the engine's own dispatch layer with
an error this layer never shaped, because it no longer owns the verb table to shape one.

All of that is read from the engine's project manager rather than pinned by a test here: this
handler sends `SetCurrentProjectRequest` and compares the engine's live workspace directory
around it, and nothing else. Reconnecting unconditionally is what makes a host correct whether
or not the reload details hold.

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
stays open. Observed by hand while running the smoke tests, and asserted by no test: a
single-threaded client that paused between requests hit a 60 second reply timeout on a healthy
socket, and a wedged client also delays delivery to the editor. `websocket_direct` gives each
connection its own unbounded queue and writer task, so a slow reader costs engine memory
instead of frames and stalls nobody. A plugin still reads on a dedicated thread that never
blocks.

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
belongs to the griptape SDK, which adds and reshapes classes on its own release cadence. Some
types the Nuke library already consumes are not in the SDK at all: `ThreeDUrlArtifact`,
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
  class describes as `GTFile` and its values may narrow to `GTImage` or `GTMovie`. A value
  carrying a source narrows only within the sourced types.
- **Sourceless is never media.** An unset value is `GTNull` and a value pointing at no bytes is
  `GTText`, whatever the parameter declared, so `GTImage`, `GTMovie`, and `GTFile` never arrive
  with an empty `sources`.
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

### Contract snapshot

The surface remains mutable until a plugin binary binds to it. Before shipping a plugin, add a snapshot that records observable names, fields, requiredness, enum members, and descriptor keys, then asserts that the frozen surface remains a subset of the current surface:

| Change | Result |
|---|---|
| Add a verb, notification, or field | passes, no version bump |
| Add a value type or source kind | passes the subset check, but the policy is a bump: a host switches on a closed set, so a new member is a case an old plugin has no branch for |
| Remove or rename any of them | **fails** |
| Make an optional field required | **fails** |
| Drop a version from the support window | **fails** |

Record the snapshot once; overwriting it would erase the compatibility baseline.

Without that guard, a rename propagated through the tests can leave the suite green.

### Uncovered compatibility risks

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

## Engine constraints

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
    times. Observed by hand, and asserted by no test: notification counts were an exact 3x
    multiple of a single-bridge run with three copies loaded. After wiring teardown, counts are
    stable across repeated runs.

    The subscription is also engine-global: listeners are keyed by event type, not by
    library or node, so an installed bridge translates and re-emits for every workflow the
    engine runs, including ones with no Nuke nodes driven from the editor. Hence installing
    on first connect rather than at load. Latching on without ever counting back down is
    deliberate, because the transport gives Python no disconnect signal; an idle timeout
    would tear the feed down exactly when a host sits quietly waiting on a long render.

4. **`broadcast_app_event` does not reach a host.** It only notifies in-process
    listeners. `put_event(AppEvent(payload=...))` is the path that reaches IPC.

5. **Result shapes vary in type, not key.** `workflow_shape` can be a
    JSON string or null.

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
    `GTImage.colorspace` is reserved and always null because adding it later as required would
    require a version bump.

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
  only mitigation.
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
- **`websocket_direct` ships disabled.** Every machine needs a config edit before a plugin can
  reach an engine. Worth an engine-side default.
- **`NukeGetParameterValuesRequest` and `NukeLoadWorkflowRequest` cost one engine request per
  declared parameter, with no transport-level batching in this layer.** A workflow's declared
  surface is knobs, not hundreds of them, so the cost has not mattered in practice. If it ever
  does, the fix is the engine's own `EventRequestBatch` wire envelope (`INTEGRATION.md`, Frame
  formats), which packs many host verb frames into one WebSocket message; it is a transport
  optimization a host applies itself, not something a handler can opt into on a host's behalf.
- **A project switch cannot say whether it reloaded libraries.** The engine's own
  `SetCurrentProjectRequest` exposes `workspace_changed` (whether workflows were
  re-registered against a new workspace) but no field for whether libraries were reloaded,
  which is gated on a separate, unexposed signal: whether the target project's
  library-affecting config differs from the outgoing project's. `NukeSetCurrentProjectRequest`
  therefore documents that a host must reconnect after every successful switch,
  unconditionally, rather than only when `workspace_changed` is true.
