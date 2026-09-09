# Nuke host API integration reference

Wire-level reference for the host side of the protocol: a Nuke NDK plugin, a Python panel,
or any process driving a Griptape Nodes engine. Assumes this library is installed in the
engine. The JSON below is illustrative, not a captured transcript; field names and shapes
are authoritative, values are examples.

Design rationale lives in `nuke_host_api/README.md`. This document covers only what a host
sends, receives, and must handle.

## Contents

- [Bound surface](#bound-surface)
- [Connecting](#connecting)
- [Frame formats](#frame-formats)
- [Read loop](#read-loop)
- [Verbs](#verbs)
- [Notifications](#notifications)
- [Value descriptors](#value-descriptors)
- [Errors](#errors)
- [Transport limits](#transport-limits)
- [Version compatibility](#version-compatibility)

## Bound surface

Defined in `nuke_host_api/protocol.py`. Not yet pinned by a recorded snapshot: no plugin
has been compiled against this version, so the surface can still change.

| Category | Members |
|---|---|
| Verbs | `NukeConnectRequest`, `NukeListWorkflowsRequest`, `NukeDescribeWorkflowRequest`, `NukeLoadWorkflowRequest`, `NukeExecuteWorkflowRequest`, `NukeGetExecutionStateRequest`, `NukeGetParameterValuesRequest`, `NukeSetParameterValuesRequest`, `NukeCancelExecutionRequest`, `NukeListProjectsRequest`, `NukeGetCurrentProjectRequest`, `NukeSetCurrentProjectRequest`, `NukeDescribeProjectRequest` |
| Notifications | `NukeNodeStateEvent`, `NukeParameterValueEvent`, `NukeExecutionStateEvent`, `NukeExecutionNodesEvent` |
| Value types | `GTImage`, `GTMovie`, `GTFile`, `GTText`, `GTNumber`, `GTBool`, `GTNull` |
| Source kinds | `path`, `url`, `inline`, `macro` |
| Parameter sections | `inputs`, `outputs` |
| Node states | `unresolved`, `running`, `resolved`, `failed` |
| Execution states | `running`, `completed`, `failed`, `cancelled` |

Binding rules:

| Rule | Reason |
|---|---|
| Bind to nothing outside the table above | Engine request and event types travel the same connection and change every release |
| Ignore unknown fields | Fields are added without a version bump; a strict parser breaks on a routine engine upgrade |
| Ignore unknown enum values, never treat as fatal | A node or execution state may gain a member within a version, and a plugin binary outlives the version bump a new value type or source kind costs |
| Never branch on `engine_version` or `engine_type` | Both are diagnostic only |

### Which verbs need a loaded workflow

`NukeListWorkflowsRequest` and `NukeDescribeWorkflowRequest` read the engine's registry and
answer for any registered workflow, loaded or not. The execution and parameter-value verbs
answer for the graph the engine currently holds and need `NukeLoadWorkflowRequest` first. The
project verbs read and change engine-wide project state and need no loaded workflow:

| Verb | Needs a loaded workflow | Takes a `workflow_id` |
|---|---|---|
| `NukeConnectRequest` | no | no |
| `NukeListWorkflowsRequest` | no | no |
| `NukeDescribeWorkflowRequest` | no | yes, required |
| `NukeListProjectsRequest` | no | no |
| `NukeGetCurrentProjectRequest` | no | no |
| `NukeSetCurrentProjectRequest` | no | no |
| `NukeDescribeProjectRequest` | no | no |
| `NukeLoadWorkflowRequest` | no, it is what loads one | yes, or a `file_path` |
| `NukeExecuteWorkflowRequest` | yes | optional, and must match what is loaded |
| `NukeGetParameterValuesRequest` | yes | no |
| `NukeSetParameterValuesRequest` | yes | no |
| `NukeGetExecutionStateRequest` | yes | no |
| `NukeCancelExecutionRequest` | yes | no |

A parameter's live value exists on a loaded node, so no read verb can select one by
`workflow_id`: for an unloaded workflow there is nothing to read. Loading is the only way to
make one readable, and it is destructive, so it is a verb of its own rather than something a
read does on a host's behalf.

## Connecting

This section and [Transport limits](#transport-limits) are read from the engine's own
`websocket_direct` implementation, at the engine floor this library declares
(`griptape-nodes-engine>=0.99.0`). No test in this repo exercises that transport: the live
smoke suite (`make test/integration/host-api`) drives `local_socket` instead. Treat config
keys, accepted paths, handshake behaviour, control frames, and queueing below as documented
engine behaviour rather than as behaviour this library pins.

A host connects over `websocket_direct`, a WebSocket server the engine binds on loopback.
The engine has two other IPC drivers and neither is the one to build a plugin on:
`websocket_api` is its outbound link to the hosted service and accepts no local
connections, and `local_socket` (Unix socket, named pipe on Windows) fans every frame out
to every client with no topic routing, drops a slow reader permanently, and serializes that
fan-out under one lock.

### 1. Enable the driver, once per machine

`websocket_direct` ships disabled. Add it to the engine config at
`$XDG_CONFIG_HOME/griptape_nodes/griptape_nodes_config.json` (`~/.config` on macOS and
Linux unless overridden), then restart the engine:

```json
{
  "ipc_drivers": [
    { "name": "websocket_api", "driver_type": "websocket_api", "enabled": true },
    { "name": "websocket_direct", "driver_type": "websocket_direct", "enabled": true,
      "host": "127.0.0.1", "port": 18125 }
  ]
}
```

Leave `websocket_api` enabled. It is the engine's link to the hosted service, and dropping
it from the list disables it.

`host` and `port` are the defaults, spelled out because a second engine on one machine
needs a second port: the engine refuses to start when the port is already bound. Keep
`host` on loopback. There is no TLS and no auth handshake, so anything that can reach the
port can drive the engine, and a routable bind address publishes that to the network.

Do **not** try to read this config over the wire. A host has no connection yet, so
`GetConfigValueRequest` cannot answer where to connect.

### 2. Open the connection

```
ws://127.0.0.1:18125/
```

The server accepts `/` and `/ws/engines/events`, with or without a query string, and
rejects any other path with a 404 during the handshake. A completed handshake is the
liveness check: connection refused means no engine is listening on that port with the
driver enabled.

**Take the URL as configuration, do not discover it.** Host and port belong in a host-side
setting (a plugin preference, a knob, an environment variable the host defines) defaulted
to `ws://127.0.0.1:18125/`. The engine does write files that look like a registry,
`engines.json` and `sessions.json` under `$XDG_DATA_HOME/griptape_nodes`, and they are
app-layer internals: their path, shape, and existence carry no compatibility promise from
this protocol, so a host that parses them binds to the one surface here that is explicitly
unversioned. The result envelope carries `engine_id` and `session_id` too, but the same
rule applies: envelope shape belongs to the wire protocol shared by the engine and every
client, not to this library, so it makes no promise either. `NukeConnectResultSuccess`
carries the engine and library versions, plus `engine_id`, `engine_name`, and `session_id`
(the engine's active session, shared engine state rather than a per-connection identity),
so what a plugin binds to comes from the one place this protocol actually versions.

### 3. Subscribe, then connect

Outbound frames are topic-routed: a connection receives a frame only if it subscribed to
that frame's topic. Two topics matter.

| Topic | Where it comes from | Carries |
|---|---|---|
| The host's reply topic | The host invents it, e.g. `nuke/reply`, and sets `response_topic` to it on every request | Results for the requests this host sent |
| `event_topic` | `NukeConnectResultSuccess.event_topic` | Every notification |

Subscribe with a text frame:

```json
{ "type": "subscribe", "topic": "nuke/reply" }
```

Order matters, because nothing is replayed:

1. Subscribe to the host's reply topic.
2. Send `NukeConnectRequest` with `response_topic` set to that topic.
3. Read the reply, then subscribe to the `event_topic` it names.

`{ "type": "unsubscribe", "topic": ... }` reverses either one. Subscriptions live on the
connection, not on the engine, so a reconnect starts again at step 1.

A request sent with no `response_topic` is not addressed to this host: its reply is
published to the engine's default response topic, the same one `event_topic` names and the
editor reads.

### 4. Filter what arrives

Topic routing narrows the stream; it does not make the stream yours.

- `event_topic` is the engine's default response topic. Every library's app events,
  execution progress, and engine chatter land there too.
- The engine subscribes every direct connection to a session's request topic when a session
  starts, so frames can arrive on a topic this host never asked for.

So the discard rule stands: drop any frame whose `request_id` is not one this host sent and
whose `payload_type` does not begin with `Nuke`.

## Frame formats

One JSON object per WebSocket text message. No newline framing, no length prefix: the
message boundary is the frame boundary. A binary frame carrying UTF-8 JSON is also
accepted.

Frames are discriminated by the top-level `type` field, absent on outbound requests.

| `type` | Direction | Discriminator for dispatch |
|---|---|---|
| absent | host to engine | `payload.request_type` |
| `subscribe`, `unsubscribe`, `ping` | host to engine | control frames, no `payload` |
| `success_result`, `failure_result` | engine to host | `payload.request_id`, then `payload.result_type` |
| `app_event` | engine to host | `payload.payload_type` |
| `pong` | engine to host | answer to `ping`, echoes `id` |

Heartbeat: send `{ "type": "ping", "id": "..." }` and the engine answers
`{ "type": "pong", "id": "..." }` on the same connection, without the frame reaching the
engine's event dispatch. Nothing pings the host, and WebSocket protocol-level ping frames
are not part of what this driver answers. A dead engine otherwise shows up as a closed
connection, or as a failure to answer a cheap `NukeGetExecutionStateRequest`.

### Requests

`request_id` is host-generated and echoed back; any value unique per in-flight request
works. `response_topic` names the topic the reply is published on, and the engine puts it
on the reply envelope. It is load-bearing: subscribe to that topic first, or the reply goes
somewhere this host is not listening.

```json
{
  "payload": {
    "event_type": "EventRequest",
    "request_type": "NukeConnectRequest",
    "request": {
      "client_protocol_versions": [1],
      "client_name": "Nuke 16.0v7"
    },
    "request_id": "9f2c...",
    "response_topic": "nuke/reply"
  }
}
```

### Batching many requests in one frame

`EventRequestBatch` is the engine's wire-only envelope for sending several requests in one
WebSocket message instead of one message each. It fans out into individual `EventRequest`
frames on ingest, so nothing here needs a batch-aware verb: each inner request still carries
its own `request_id` and `response_topic`, and results come back as ordinary
`success_result`/`failure_result` frames correlated by `request_id`, exactly as if each had
been sent separately. There is no batched reply to wait for.

```json
{
  "payload": {
    "event_type": "EventRequestBatch",
    "requests": [
      {
        "event_type": "EventRequest",
        "request_type": "NukeGetParameterValuesRequest",
        "request": { "sections": ["inputs"] },
        "request_id": "batch-1a",
        "response_topic": "nuke/reply"
      },
      {
        "event_type": "EventRequest",
        "request_type": "NukeGetExecutionStateRequest",
        "request": {},
        "request_id": "batch-1b",
        "response_topic": "nuke/reply"
      }
    ]
  }
}
```

`EventRequestBatch` belongs to the engine's own wire envelope
(`retained_mode/events/base_events.py`), not to this protocol: it appears in neither the `Verb`
list nor the Bound surface table, so its shape can change without a `PROTOCOL_VERSION` bump.
The shape above is read from the envelope's `dict()`/`from_dict()` contract and has not been
exercised through `websocket_direct`. A host that uses it must tolerate engine-level changes
to the envelope. It is worth that for a plugin wanting several verbs answered in one network
round trip, for example reading parameter values and execution state on a single poll tick,
instead of one WebSocket message per verb.

### Results

Outcome in `payload.result`, concrete type in `payload.result_type`, original request
echoed in `payload.request`.

```json
{
  "type": "success_result",
  "topic": "nuke/reply",
  "payload": {
    "engine_id": "a69c283e-...",
    "session_id": "50c24f47-...",
    "request": { "...echoed..." },
    "request_id": "9f2c...",
    "result_type": "NukeConnectResultSuccess",
    "result": { "...payload..." }
  }
}
```

### App events

Unsolicited. Other libraries and the engine broadcast on the same topic, so filter for
`payload_type` values beginning with `Nuke`.

```json
{
  "type": "app_event",
  "topic": "sessions/50c24f47.../response",
  "payload": {
    "payload_type": "NukeNodeStateEvent",
    "event_type": "AppEvent",
    "payload": {
      "node_name": "Start Flow",
      "state": "unresolved",
      "detail": ""
    }
  }
}
```

## Read loop

Results and notifications arrive interleaved on one connection. A client that reads until
it finds its reply and discards everything else drops every notification.

Required loop:

1. Read a frame.
2. If it is a notification, dispatch it and keep reading.
3. If it carries the awaited `request_id`, it is the reply.
4. Otherwise discard it.

Implement this as a pump that owns the connection, not as a request-response helper that
returns after one read.

## Verbs

### NukeConnectRequest

Subscribe to a reply topic first, then connect. Required before expecting notifications; the
other verbs answer without it.

| Request field | Type | Default | Notes |
|---|---|---|---|
| `client_protocol_versions` | `list[int]` | `[]` | Every version the host can speak. Empty means "assume current" |
| `client_name` | `str` | `""` | Free text for logs and support tickets |

| `NukeConnectResultSuccess` field | Type | Notes |
|---|---|---|
| `protocol_version` | `int` | Highest mutual version. Use only this version's vocabulary for the session |
| `supported_protocol_versions` | `list[int]` | Full support window, diagnostic |
| `engine_version` | `str` | Display only |
| `library_version` | `str` | Display only |
| `event_topic` | `str` | The topic notifications are published on. Subscribe to it or receive none |
| `value_types` | `list[str]` | Closed value type set for this version |
| `engine_id` | `str` | The engine's own id. Empty when the engine has not set one |
| `session_id` | `str` | The engine's active session, shared engine state, not this connection's own. Empty when no session is open |
| `engine_name` | `str` | Human-readable. Empty when the engine could not report one |

**Connect before expecting notifications.** The outbound event bridge installs on the first
`NukeConnectRequest` rather than at library load, so an engine no host has spoken to does not
pay to translate and re-emit every execution event it runs. A host that skips connect and
goes straight to executing gets replies and no events, with no error to explain it.
Subscribing to `event_topic` without connecting fails the same way: nothing is publishing
yet.

```json
{
  "protocol_version": 1,
  "supported_protocol_versions": [1],
  "engine_version": "0.99.0",
  "library_version": "0.3.0",
  "event_topic": "sessions/50c24f4744a4463084ea3a701644993a/response",
  "value_types": ["GTImage", "GTMovie", "GTFile", "GTText", "GTNumber", "GTBool", "GTNull"],
  "engine_id": "a69c283e-...",
  "session_id": "50c24f47-...",
  "engine_name": "Dan's workstation"
}
```

`NukeConnectResultFailure` carries `supported_protocol_versions` and a message naming the
window, suitable for display to a user:

```json
{
  "supported_protocol_versions": [1],
  "result_details": {
    "result_details": [
      {
        "level": 40,
        "message": "Attempted to connect a host speaking protocol version(s) [99]. Failed because this library supports [1]. Update the host plugin, or install a library version that still supports it."
      }
    ]
  }
}
```

### NukeListWorkflowsRequest

| Request field | Type | Default | Notes |
|---|---|---|---|
| `runnable_only` | `bool` | `true` | `false` returns unavailable workflows too, for diagnostic lists |

`NukeListWorkflowsResultSuccess.workflows` entries:

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Opaque key for every later call. Do not parse or display |
| `name` | `str` | Display label |
| `description` | `str` | |
| `runnable` | `bool` | True when the workflow declares an input/output shape and its file is still on disk |
| `unavailable_reason` | `str` | Why an entry is greyed out. Empty when runnable |

```json
{
  "workflows": [
    {
      "id": "nuke_api_smoke",
      "name": "Nuke API Smoke",
      "description": "",
      "runnable": true,
      "unavailable_reason": ""
    }
  ]
}
```

### NukeDescribeWorkflowRequest

| Request field | Type | Notes |
|---|---|---|
| `workflow_id` | `str` | Required |

| `NukeDescribeWorkflowResultSuccess` field | Type | Notes |
|---|---|---|
| `workflow_id` | `str` | Echoed |
| `name` | `str` | |
| `description` | `str` | |
| `inputs` | `list[dict]` | Parameter descriptors |
| `outputs` | `list[dict]` | Parameter descriptors. The only definition of "outputs" in this protocol |

Parameter descriptor fields:

| Field | Notes |
|---|---|
| `node` | Node name. Addresses inputs in `NukeExecuteWorkflowRequest` |
| `parameter` | Parameter name. Addresses inputs in `NukeExecuteWorkflowRequest` |
| `name` | Pre-joined `node.parameter` label for display |
| `type` | Always one of the seven value types |
| `default` | The workflow author's default, as a value descriptor. Initialize the knob to this |
| `tooltip` | Help text for the knob. Empty when the author wrote none |
| `settable` | False means the engine will refuse a value. Build the knob read-only |

`default` is a full value descriptor rather than a raw value, so a parameter's default and its
live value are the same shape and one code path renders both. A parameter with no author default
reports `GTNull` with no sources.

Every field is always present. A parameter the engine gave no metadata for reports `GTNull`, an
empty tooltip, and `settable: true` rather than omitting keys.

**`type` can be narrower at runtime.** `type` is built from the declared type name, before any
value exists; a descriptor's `value_type` is built from the value itself. They differ in one
direction only, by narrowing:

| Declared type says | `type` reports | A value may arrive as |
|---|---|---|
| A media type or scalar (`ImageUrlArtifact`, `Sequence`, `int`, `bool`) | that type | that type, or one of the two overrides below |
| An artifact class this version does not map (`GenericArtifact`) | `GTFile` | `GTFile`, `GTImage`, `GTMovie`, or one of the two overrides below |
| A wildcard (`any`, `all`) | `GTText` | anything |

Two overrides apply to every parameter, whatever it declares:

- **Unset is `GTNull`.** An image parameter holding nothing reports `GTNull` with no sources,
  not `GTImage`.
- **Pointing at no bytes is `GTText`.** A value with no usable locator reports `GTText`, because
  prose on an image parameter is still prose and `GTImage` with an empty `sources` would promise
  bytes that do not exist. So `GTImage`, `GTMovie`, and `GTFile` never arrive sourceless.

A `GenericArtifact` parameter holding `https://cdn.example.com/still.jpg` is genuinely an image,
and nothing at describe time can know that, because no value exists yet. So build the knob
from `type` and always switch on the descriptor's `value_type` when a value actually
arrives. Never branch on the declared type at runtime.

```json
{
  "workflow_id": "nuke_api_smoke",
  "name": "Nuke API Smoke",
  "description": "",
  "inputs": [
    {
      "node": "Start Flow",
      "parameter": "topic",
      "name": "Start Flow.topic",
      "type": "GTText",
      "default": {
        "value_type": "GTText",
        "sources": [],
        "colorspace": null,
        "engine_type": "str"
      },
      "tooltip": "What the shot is about.",
      "settable": true
    }
  ],
  "outputs": [
    {
      "node": "End Flow",
      "parameter": "was_successful",
      "name": "End Flow.was_successful",
      "type": "GTBool",
      "default": {
        "value_type": "GTNull",
        "sources": [],
        "colorspace": null,
        "engine_type": "NoneType"
      },
      "tooltip": "",
      "settable": true
    },
    {
      "node": "End Flow",
      "parameter": "result_details",
      "name": "End Flow.result_details",
      "type": "GTText",
      "default": {
        "value_type": "GTNull",
        "sources": [],
        "colorspace": null,
        "engine_type": "NoneType"
      },
      "tooltip": "",
      "settable": true
    },
    {
      "node": "End Flow",
      "parameter": "summary",
      "name": "End Flow.summary",
      "type": "GTText",
      "default": {
        "value_type": "GTNull",
        "sources": [],
        "colorspace": null,
        "engine_type": "NoneType"
      },
      "tooltip": "",
      "settable": true
    }
  ]
}
```

Build host knobs from this. Control-flow parameters are already removed, so every listed parameter
carries data.

### NukeLoadWorkflowRequest

Puts a workflow in the engine and returns everything needed to build and initialize knobs:
the declared parameters and their current values, for both sides, in one reply. Required
before `NukeExecuteWorkflowRequest`, `NukeGetParameterValuesRequest`, or
`NukeGetExecutionStateRequest` can answer for the workflow a host means.

**Destructive.** The engine clears all object state to load a graph, so this discards whatever
was loaded before, including a graph an editor user has open on the same engine. Confirm with
the artist before sending it. It clears before it knows the load will succeed, so a failed load
can leave nothing loaded at all.

| Request field | Type | Default | Notes |
|---|---|---|---|
| `workflow_id` | `str` | `""` | From `NukeListWorkflowsRequest`. Mutually exclusive with `file_path` |
| `file_path` | `str` | `""` | Absolute path to a workflow file the engine has not registered. Imported, registered, then loaded. Mutually exclusive with `workflow_id` |

Send exactly one. Both is refused rather than resolved, because they can name different
workflows; neither is refused too.

| `NukeLoadWorkflowResultSuccess` field | Type | Notes |
|---|---|---|
| `workflow_id` | `str` | The loaded workflow's id. Resolved from `file_path` when that is what was sent, so this is how a host learns the id to use afterwards |
| `name` | `str` | Display label |
| `description` | `str` | |
| `inputs` | `list[dict]` | Declared start-flow parameter descriptors, identical to `NukeDescribeWorkflowResultSuccess.inputs`. Build knobs from these |
| `outputs` | `list[dict]` | Declared end-flow parameter descriptors |
| `input_values` | `dict` | `{node: {parameter: value_descriptor}}`, identical in shape to `NukeGetParameterValuesResultSuccess.inputs`. Initialize knobs to these |
| `output_values` | `dict` | Same shape, end-flow side. Carries real values for a workflow that has run before, empty descriptors for one that has not |
| `unavailable` | `list[dict]` | `{section, node, parameter, reason}` for declared parameters the engine would not read. Reported, not omitted |

Four fields rather than two because a parameter's declaration and its current value are
different questions: the declaration is fixed for the workflow, the value changes on every
run. Both shapes are ones a host already parses from describe and from the bulk read verb, so
there is nothing new to write.

**Initialize knobs from `input_values`, not from a descriptor's `default`.** `default` is the
workflow author's value; `input_values` is what the graph currently holds. They differ for any
workflow whose inputs have been touched.

```json
{ "workflow_id": "nuke_api_smoke" }
```

```json
{
  "workflow_id": "nuke_api_smoke",
  "name": "Nuke API Smoke",
  "description": "",
  "inputs": [
    {
      "node": "Start Flow",
      "parameter": "topic",
      "name": "Start Flow.topic",
      "type": "GTText",
      "default": {
        "value_type": "GTText",
        "sources": [],
        "colorspace": null,
        "engine_type": "str"
      },
      "tooltip": "What the shot is about.",
      "settable": true
    }
  ],
  "outputs": [
    {
      "node": "End Flow",
      "parameter": "was_successful",
      "name": "End Flow.was_successful",
      "type": "GTBool",
      "default": {
        "value_type": "GTNull",
        "sources": [],
        "colorspace": null,
        "engine_type": "NoneType"
      },
      "tooltip": "",
      "settable": true
    }
  ],
  "input_values": {
    "Start Flow": {
      "topic": {
        "value_type": "GTText",
        "sources": [],
        "colorspace": null,
        "engine_type": "str"
      }
    }
  },
  "output_values": {
    "End Flow": {
      "was_successful": {
        "value_type": "GTNull",
        "sources": [],
        "colorspace": null,
        "engine_type": "NoneType"
      }
    }
  },
  "unavailable": []
}
```

Loading a file the engine has never seen:

```json
{ "file_path": "/shots/sq010/comp_v012.py" }
```

Refused, and nothing is loaded:

| Condition | `because` names |
|---|---|
| Both `workflow_id` and `file_path` | that they may name different workflows |
| Neither | that there is nothing to load |
| A run is in progress | that loading discards the running graph, and `NukeCancelExecutionRequest` |
| The file cannot be imported | the engine's own reason |
| The id is not registered | that no workflow with that name exists |
| The registry cannot be read | that the engine could not read it, which is worth retrying |
| The engine could not load the workflow | the engine's own reason, and that the previous graph is already gone |

Every row but the last leaves the loaded graph exactly as it was, so the knobs a host is
showing still match what the engine holds. A `file_path` request is the one that touches
anything else: the file is imported and registered before the rows below it are checked, so a
refusal there can leave a new registry entry behind. The last row cannot leave the graph alone:
`run_with_clean_slate` makes the engine clear all object state before it builds the graph, so a
workflow that fails inside its own file, on a missing library or an exception, leaves nothing
loaded. That failure alone carries `engine_state_cleared: true`.

Branch on `engine_state_cleared`, not on the reason text. When it is `false`, the knobs a host
is showing still match what the engine holds and a retry is free. When it is `true`, the graph
the host was driving is gone: drop the knobs, and tell the artist before retrying, because the
comp they had open went with it.

| `NukeLoadWorkflowResultFailure` field | Type | Notes |
|---|---|---|
| `workflow_id` | `str` | The id asked for, or the one resolved from `file_path`. Empty when the request never got far enough to name one |
| `engine_state_cleared` | `bool` | `true` only when the engine had already discarded the previous graph before it failed |

### NukeExecuteWorkflowRequest

Applies inputs to the loaded workflow and starts it. Loads nothing: call
`NukeLoadWorkflowRequest` first. Returns once execution has started; progress and the terminal
state arrive as notifications.

| Request field | Type | Default | Notes |
|---|---|---|---|
| `workflow_id` | `str` | `""` | Optional. Empty runs whatever is loaded. Set, it must be the loaded workflow or the request is refused |
| `inputs` | `dict[str, dict[str, Any]]` | `{}` | `{node: {parameter: value}}` keyed by describe's `node` and `parameter`. Plain JSON values |

Send `workflow_id` if the host tracks what it loaded. It costs nothing and turns a graph
swapped out from under the host, by an editor user or another tool, into a refusal instead of a
run of the wrong workflow. Leave it empty to drive a graph the host did not load itself.

| `NukeExecuteWorkflowResultSuccess` field | Type | Notes |
|---|---|---|
| `workflow_id` | `str` | The workflow that ran. Always the loaded one, so a host that sent no id still learns what it started |
| `state` | `str` | An execution state |
| `applied_inputs` | `list[dict]` | `{node, parameter}` the engine accepted |
| `rejected_inputs` | `list[dict]` | `{node, parameter, reason}` |

```json
{
  "workflow_id": "nuke_api_smoke",
  "inputs": {
    "Start Flow": {
      "topic": "a quiet harbour at dusk"
    }
  }
}
```

```json
{
  "workflow_id": "nuke_api_smoke",
  "state": "running",
  "applied_inputs": [
    {
      "node": "Start Flow",
      "parameter": "topic"
    }
  ],
  "rejected_inputs": []
}
```

Check `rejected_inputs` on every execution. A rejection does not fail the execution: the
workflow executes with whatever value was already present and returns plausible output
computed from the wrong input. Surface rejections immediately.

Two kinds are turned away before the engine sees them, and both are the host's own to fix. A
`node` whose value is not an object of parameters is rejected with
`"Expected an object of parameters."` and `parameter` set to `"*"`, since no single parameter
was named; do not look `"*"` up in what describe returned. A pair that is not a declared input
parameter is rejected with `"Not a declared input parameter of this workflow."`; address inputs
only by the `node` and `parameter` `NukeDescribeWorkflowRequest` or `NukeLoadWorkflowRequest`
returned.

Any other reason is the engine's own, on a declared pair that was already forwarded when it was
refused. Split on that rather than on counting kinds: a reason the host did not write above is
the engine's.

Sending inputs to a loaded graph that declares no input parameters is refused instead, rather
than rejecting every one of them. The case a host meets is an unsaved graph: with `workflow_id`
empty, execute runs whatever the engine holds, and the graph an editor user is working on lives
in the engine's registry under an `unsaved:` key with no declared shape. Rejecting each input
there would hand the host its own parameter names back as if they were wrong, while the run
went ahead on the author's values. The refusal says to save the workflow and load it by id, or
to send no inputs and run it as it stands.

A registry the engine cannot read gets a separate refusal, naming a retry, and so does a loaded
id that is no longer in the registry at all, naming a reload. All three leave the same empty
allow-list behind, so they are easy to conflate, but only one of them is the host's to fix by
saving: a workflow that declares nothing still will next time, while the other two are engine
state that moved. A host told to save a workflow it already saved has been sent down the wrong
recovery path.

None of the three fires when `inputs` is empty. With nothing to check, what the workflow declares
does not bear on the run, so a graph with no declared shape still executes.

A `workflow_id` naming anything other than the loaded workflow is refused, not loaded.
Honouring it would make execute destructive; ignoring it would run a workflow the host did not
ask for while reporting success. The refusal names both ids and says to load first.

Nothing loaded is also a refusal, naming `NukeLoadWorkflowRequest`.

One execution at a time. Starting a run while one is in progress returns
`NukeExecuteWorkflowResultFailure` rather than displacing it, because the engine threads no
execution identifier through its execution events: a second run's notifications would be
indistinguishable from the first's, and a cancel could not say which to stop. Poll
`NukeGetExecutionStateRequest` for `running: false`, or wait for the terminal
`NukeExecutionStateEvent`, before starting the next one. An execution id would arrive as an
added field, which a tolerant parser already handles.

### NukeGetExecutionStateRequest

The running-state recovery path. Notifications have no replay, so a host that connected
mid-execution or dropped its connection has permanently missed events; this call returns
current truth read live from the engine, with no cache that could disagree. It is also how
a host checks whether it may start another run.

No request fields. Reports execution state only; a workflow's parameter values are a separate
read, `NukeGetParameterValuesRequest`, because each one costs an engine round trip per parameter and
a host polling only for liveness should not pay for it.

| `NukeGetExecutionStateResultSuccess` field | Type | Notes |
|---|---|---|
| `running` | `bool` | Whether anything is executing |
| `active_nodes` | `list[str]` | Nodes currently resolving |
| `involved_nodes` | `list[str]` | Nodes in the current execution |
| `workflow_id` | `str` | Loaded workflow, empty when none |

```json
{
  "running": false,
  "active_nodes": [],
  "involved_nodes": [],
  "workflow_id": "nuke_api_smoke"
}
```

### NukeGetParameterValuesRequest

The bulk value-reading path. Reads every declared start-flow or end-flow parameter's
current value in one call instead of one `GetParameterValueRequest`-per-parameter round trip a
host would otherwise have to issue itself. Values exist only for the loaded graph, so this
takes no `workflow_id`: it always answers for whatever `NukeLoadWorkflowRequest` most recently
loaded.

`NukeLoadWorkflowRequest` already returns these values once. This is the verb for reading them
again: after a run finishes, or after a reconnect that missed every notification. Both go
through one reader in the library, so they cannot disagree.

| Request field | Type | Default | Notes |
|---|---|---|---|
| `sections` | `list[str]` | `[]` | One or more of `inputs`, `outputs`. Empty means both. An unrecognized name is refused, not silently ignored |

| `NukeGetParameterValuesResultSuccess` field | Type | Notes |
|---|---|---|
| `workflow_id` | `str` | The workflow these values belong to |
| `requested_sections` | `list[str]` | The sections actually read, so a host can tell "not asked for" from "asked for, got nothing" |
| `inputs` | `dict` | `{node: {parameter: value_descriptor}}` for the start-flow side, matching describe's `inputs`. Empty when `inputs` was not requested or the workflow declares none |
| `outputs` | `dict` | Same shape, for the end-flow side, matching describe's `outputs` |
| `unavailable` | `list[dict]` | `{section, node, parameter, reason}` for declared parameters the engine would not answer for. Reported, not omitted: an absent entry and an empty one mean different things to a host building a knob |

```json
{
  "workflow_id": "nuke_api_smoke",
  "requested_sections": ["inputs", "outputs"],
  "inputs": {
    "Start Flow": {
      "topic": {
        "value_type": "GTText",
        "sources": [],
        "colorspace": null,
        "engine_type": "str"
      }
    }
  },
  "outputs": {
    "End Flow": {
      "was_successful": {
        "value_type": "GTBool",
        "sources": [],
        "colorspace": null,
        "engine_type": "bool"
      },
      "result_details": {
        "value_type": "GTText",
        "sources": [],
        "colorspace": null,
        "engine_type": "str"
      },
      "summary": {
        "value_type": "GTText",
        "sources": [],
        "colorspace": null,
        "engine_type": "str"
      }
    }
  },
  "unavailable": []
}
```

Asking for only one side:

```json
{ "sections": ["inputs"] }
```

A name outside `inputs`/`outputs` fails rather than answering with nothing:

```json
{ "sections": ["sideways"] }
```

```json
{
  "result_details": {
    "result_details": [
      {
        "level": 40,
        "message": "Attempted to read declared parameter values. Failed because section(s) ['sideways'] are not recognized. Use one or more of ['inputs', 'outputs']."
      }
    ]
  }
}
```

### NukeSetParameterValuesRequest

The write half of `NukeGetParameterValuesRequest`: sets values on the loaded workflow's
declared inputs without starting a run, for a host that wants to stay live with the engine as
an artist edits a knob rather than only diverging locally until the next
`NukeExecuteWorkflowRequest`. Loaded-state-addressed like the read verb, so it takes no
`workflow_id` either.

| Request field | Type | Default | Notes |
|---|---|---|---|
| `inputs` | `dict[str, dict[str, Any]]` | `{}` | `{node: {parameter: value}}` keyed by describe's `node` and `parameter`. Plain JSON values. A request with no pair to act on is refused, not answered as a trivial success: that covers an empty `inputs` and one where every node maps to an empty parameter dict |

| `NukeSetParameterValuesResultSuccess` field | Type | Notes |
|---|---|---|
| `workflow_id` | `str` | The workflow the values were applied to |
| `applied_inputs` | `list[dict]` | `{node, parameter}` the engine accepted |
| `rejected_inputs` | `list[dict]` | `{node, parameter, reason}` |

```json
{
  "inputs": {
    "Start Flow": {
      "topic": "a quiet harbour at dusk"
    }
  }
}
```

```json
{
  "workflow_id": "nuke_api_smoke",
  "applied_inputs": [
    {
      "node": "Start Flow",
      "parameter": "topic"
    }
  ],
  "rejected_inputs": []
}
```

Same allow-list, same two host-side rejection reasons, and the same rule that a rejection is
not a failure of the request, as `NukeExecuteWorkflowRequest`: see that verb's section above
for `"Expected an object of parameters."`, `"Not a declared input parameter of this
workflow."`, and how the engine's own reason for refusing a declared pair reaches the host.
Sending a request with no pair to act on is refused here, unlike execute, because there is
nothing else for this verb to do; `NukeExecuteWorkflowRequest` treats empty inputs as "run the
graph as it stands." A loaded graph that declares no input parameters, and a registry the
engine cannot read, are refused the same two causes execute refuses them for, worded without
the fallback execute offers: `NukeExecuteWorkflowRequest`'s versions of these two refusals end
with "or send no inputs to run the graph as it stands," and this verb's do not, since sending
no inputs is exactly what this verb's own empty-request refusal turns away. A loaded id no
longer in the registry is refused the same third way execute refuses it: that refusal names no
fallback either way.

Refused while the engine is executing. The engine's own scheduler decides when a node's
parameter is actually read, so a value set mid-run cannot be told apart from one that lands
before the node that consumes it or one that lands after, and this layer must not answer as if
it knows which. Wait for `NukeGetExecutionStateRequest` to report `running: false`, or the
terminal `NukeExecutionStateEvent`, or cancel with `NukeCancelExecutionRequest`, then retry.

### NukeCancelExecutionRequest

No arguments. Cancels whatever is running.

| Behaviour | Detail |
|---|---|
| Success reply | Cancellation requested only. Not confirmation that execution stopped |
| Terminal state | Arrives as `NukeExecutionStateEvent` with `state: "cancelled"` |
| Nothing running | Returns `NukeCancelExecutionResultFailure` rather than a silent no-op |

### NukeListProjectsRequest

Workflows are registered per workspace and a project decides the workspace, so this and
the next three verbs let a host see which project the engine is on and change it.

| Request field | Type | Default | Notes |
|---|---|---|---|
| `include_system_builtins` | `bool` | `false` | `true` also lists the system defaults entry |

`NukeListProjectsResultSuccess.projects` entries:

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Opaque. Feed to `NukeSetCurrentProjectRequest` or `NukeDescribeProjectRequest`. Do not parse or display |
| `name` | `str` | Display label. Empty for a failed entry rather than falling back to the opaque `id` |
| `description` | `str` | Always empty here. Read `NukeDescribeProjectRequest` for the real value |
| `file_path` | `str` | Absolute path to the project's YAML. Empty only for a project with no backing file (the system defaults); a failed entry's `id` is already that path, so it is reused here |
| `parent_id` | `str` | The parent project's id, empty when this project has no parent |
| `current` | `bool` | True for the project the engine is on right now |
| `available` | `bool` | False when the template failed validation, or when its adjacent config requires an engine version this engine fails |
| `unavailable_reason` | `str` | Why an entry is greyed out. Empty when `available` |

```json
{
  "projects": [
    {
      "id": "proj-1",
      "name": "Nuke Smoke Project",
      "description": "",
      "file_path": "/projects/proj-1/griptape-nodes-project.yml",
      "parent_id": "",
      "current": true,
      "available": true,
      "unavailable_reason": ""
    }
  ]
}
```

### NukeGetCurrentProjectRequest

No arguments.

| `NukeGetCurrentProjectResultSuccess` field | Type | Notes |
|---|---|---|
| `id` | `str` | Opaque, as above |
| `name` | `str` | |
| `description` | `str` | Empty when the author wrote none |
| `file_path` | `str` | Empty for a project with no backing file, the system defaults project |
| `base_dir` | `str` | Directory this project resolves its own relative paths against. Diagnostic |
| `workspace_dir` | `str` | The workspace directory the engine is actually using right now, read live. Never empty, including on the system defaults project |
| `validation_status` | `str` | One of `GOOD`, `FLAWED`, `UNUSABLE`, `MISSING`. `GOOD` and `FLAWED` are usable; the other two are not |
| `problems` | `list[str]` | Human-readable validation messages, for display. Empty when `validation_status` is `GOOD` |

`NukeGetCurrentProjectResultFailure` means no current project is set at all, which the
engine treats as distinct from being on the system defaults project.

```json
{
  "id": "proj-1",
  "name": "Nuke Smoke Project",
  "description": "",
  "file_path": "/projects/proj-1/griptape-nodes-project.yml",
  "base_dir": "/projects/proj-1",
  "workspace_dir": "/workspace/proj-1",
  "validation_status": "GOOD",
  "problems": []
}
```

### NukeSetCurrentProjectRequest

| Request field | Type | Default | Notes |
|---|---|---|---|
| `project_id` | `str \| null` | `null` | Id from `NukeListProjectsRequest` or `NukeGetCurrentProjectRequest`. `null` requests the system defaults, mirroring the engine's own request exactly |

| `NukeSetCurrentProjectResultSuccess` field | Type | Notes |
|---|---|---|
| `project_id` | `str` | The id actually activated, resolved from a requested `null` to the engine's system-defaults id |
| `workspace_changed` | `bool` | Whether the engine's live workspace directory differs from the one active immediately before this call |

Refuses while the engine is executing, with `NukeSetCurrentProjectResultFailure` worded like
`NukeExecuteWorkflowRequest`'s running-guard: reloading libraries under a live run is worse
than refusing, since the very library driving the run could be torn down and rebuilt
mid-flight. The engine also leaves the previously active project active on any failure.

**Always reconnect after a successful switch, whatever `workspace_changed` says.** Beyond
re-registering workflows on a workspace change, the engine separately reloads every
library, this one included, whenever the target project's library-affecting config differs
from the outgoing project's, and that decision is made independently of
`workspace_changed`: a switch can reload every library while its workspace stays the same,
or leave every library untouched while its workspace changes. The engine exposes no field
for that decision, so this result cannot say after the fact whether it happened. A reload
tears down this library's request handlers and its outbound event bridge and rebuilds
both, so a host that keeps talking on its old connection without reconnecting may find
every notification has silently stopped, and its cached results from `NukeListWorkflowsRequest`
and `NukeDescribeWorkflowRequest` are stale regardless of whether the reload happened. Send
`NukeConnectRequest` again immediately after reading this result, then re-run
`NukeListWorkflowsRequest` and `NukeDescribeWorkflowRequest` for anything the host plans to
run next.

The reload behaviour above is read from the engine's project manager, not pinned by a test in
this repo: this handler only sends `SetCurrentProjectRequest` and compares the engine's live
workspace directory before and after. That the reply survives a reload has the same standing,
and rests on the engine reloading synchronously while handling the request, before the reply is
built. Reconnecting unconditionally is what makes a host correct either way.

If the target project's workspace does not configure this library at all, the reload
removes this library's verbs entirely, and every request after that, including the
reconnect, fails at the engine's own dispatch layer with an error this layer never shaped,
because it no longer owns the verb table to shape one. There is nothing a host can do about
that beyond restoring a project that does configure this library, from outside this
protocol.

```json
{ "project_id": "proj-2" }
```

```json
{ "project_id": "proj-2", "workspace_changed": true }
```

### NukeDescribeProjectRequest

Preview a project's workspace and validation before activating it with
`NukeSetCurrentProjectRequest`.

| Request field | Type | Notes |
|---|---|---|
| `project_id` | `str` | Required. From `NukeListProjectsRequest` |

| `NukeDescribeProjectResultSuccess` field | Type | Notes |
|---|---|---|
| `project_id` | `str` | Echoed |
| `name` | `str` | |
| `description` | `str` | Empty when the author wrote none |
| `workspace_dir` | `str` | The workspace directory this project would resolve to if activated, empty when the id resolves to no readable project file |
| `validation_status` | `str` | One of `GOOD`, `FLAWED`, `UNUSABLE`, `MISSING` |
| `problems` | `list[str]` | Human-readable validation messages |

```json
{
  "project_id": "proj-2",
  "name": "Second Unit Project",
  "description": "",
  "workspace_dir": "/workspace/proj-2",
  "validation_status": "GOOD",
  "problems": []
}
```

## Notifications

Pushed without a request, labelled with `event_topic`. Nine engine execution event types
collapse into these four notifications.

### NukeNodeStateEvent

| Field | Type | Notes |
|---|---|---|
| `node_name` | `str` | |
| `state` | `str` | `unresolved`, `running`, `resolved`, `failed` |
| `detail` | `str` | Error text when failed, otherwise empty |

```json
{
  "node_name": "Start Flow",
  "state": "unresolved",
  "detail": ""
}
```

### NukeParameterValueEvent

| Field | Type | Notes |
|---|---|---|
| `node_name` | `str` | |
| `parameter_name` | `str` | |
| `value` | `dict` | Normalized value descriptor. Never a raw engine artifact |

```json
{
  "node_name": "End Flow",
  "parameter_name": "was_successful",
  "value": {
    "value_type": "GTBool",
    "sources": [],
    "colorspace": null,
    "engine_type": "bool"
  }
}
```

### NukeExecutionStateEvent

Terminal notification.

| Field | Type | Notes |
|---|---|---|
| `state` | `str` | In practice only `completed` or `cancelled` arrive on this notification. `running` is reported on `NukeExecuteWorkflowResultSuccess` instead, and `failed` is reserved (see below) |
| `terminal_node` | `str` | Node control flow ended on. Diagnostic, often not a declared output node |
| `detail` | `str` | Human-readable reason |

```json
{
  "state": "completed",
  "terminal_node": "End Flow",
  "detail": "The engine reported the flow finished. It did not report an outcome."
}
```

`completed` means only that the engine finished the flow, not that it succeeded. The
engine's `ControlFlowResolvedEvent` fires on both a clean run and an errored one and
carries no status field, so this layer has nothing else to report. `failed` is reserved
for the day the engine exposes that outcome on an event; it is not emitted today. The
only way to detect an actual failure is to catch the live `NukeNodeStateEvent` with
`state: "failed"` as it is pushed. `NukeGetExecutionStateRequest` cannot recover a missed
one after the fact: its result carries running state and active/involved nodes, never a
flow-level outcome, because the engine exposes none. `NukeGetParameterValuesRequest` reads
values, a separate call with a separate purpose, and it carries no outcome either. A host
that drops its connection or connects late has no way to learn, after the fact, that a run
failed.

May also receive `cancelled` followed by `completed` for one run: the engine's cancel and
error paths both end in the same completion event, and whether a host observes both for a
single run is a timing question this layer cannot settle by reading engine source. Treat
the first terminal state received as authoritative and ignore a later one for the same run.

Carries no outputs by design. Outputs mean exactly one thing in this protocol: the parameters
`NukeDescribeWorkflowRequest` declared. Read them with `NukeGetParameterValuesRequest`.

### NukeExecutionNodesEvent

The progress bar's denominator. `NukeNodeStateEvent` with `state: "resolved"` is the
numerator a host already tracks per node; this notification, translated from the engine's own
`InvolvedNodesEvent`, is the run's node set.

| Field | Type | Notes |
|---|---|---|
| `involved_nodes` | `list[str]` | Nodes participating in the current execution |

```json
{
  "involved_nodes": ["Start Flow", "Blur", "End Flow"]
}
```

Not one-shot and not a participant count. The engine emits one non-empty list per flow it
starts, and one empty list when the top-level run finishes. The top-level flow's list arrives
first, carrying every node that flow declares.

Subflows emit too. A graph holding a `WorkflowNode`, a `SubflowNodeGroup`, or a loop node starts
an isolated flow per execution, and the engine guards that emission only on start node against
end node, so each subflow adds a non-empty list of its own nodes. The payload carries no flow
name, and this layer cannot add one.

Read them by arrival order: the first non-empty list is the run's total, every later non-empty
list is a nested scope and not a correction to the total, and the empty one means the top-level
run finished rather than "zero nodes ran". For a total that does not depend on arrival order,
read `NukeGetExecutionStateRequest`'s `involved_nodes`, which the engine derives from the named
flow's declared nodes rather than from event history.

The total counts what a flow declares, not what its control path reaches, so a graph with an
untaken branch never resolves every node on the list and the ratio of `resolved` counts to its
length can stay below 1.0 on a clean run. Execution mode does not change any of this, and a flow
whose start node is also its end node emits no non-empty list at all, so tolerate a run with no
total.

Both events for a run are dispatched by the engine before `NukeExecuteWorkflowRequest`'s own
reply is written, so a plugin cannot wait for that reply before reading this notification for
a one-time total: subscribe to `event_topic` as part of connecting, per "Subscribe, then
connect" above, and read every event on it throughout the run, not only after execute's reply
arrives. A plugin that reconnects mid-run, or otherwise missed the live stream, reads
`NukeGetExecutionStateRequest`'s `involved_nodes` for the engine's current answer instead.

Not reported on `NukeExecuteWorkflowResultSuccess`. That reply is written before parallel
resolution has necessarily discovered its full node set, so a field there would either be
incomplete or cost an extra engine round trip execute does not otherwise need. This
notification is the engine's own live count, already free on the event stream a host is
already subscribed to.

## Value descriptors

Every value, in a notification or in `inputs`/`outputs` from `NukeGetParameterValuesRequest`,
has this shape:

```json
{
  "value_type": "GTImage",
  "sources": [
    {
      "kind": "path",
      "value": "/…/outputs/render.####.exr",
      "format": "exr",
      "width": null,
      "height": null,
      "byte_count": null,
      "is_pattern": true,
      "raw": "{outputs}/render.{###}.exr"
    }
  ],
  "colorspace": null,
  "engine_type": "ImageUrlArtifact"
}
```

| Field | Notes |
|---|---|
| `value_type` | The only field to switch on |
| `sources` | Zero or more locators. Multiple sources means a sequence |
| `colorspace` | Always null in v1, reserved |
| `engine_type` | Support diagnostics only. Will change; never branch on it |

### Value types

| `value_type` | Meaning |
|---|---|
| `GTImage` | One or more images. Multiple sources means a sequence |
| `GTMovie` | A movie file |
| `GTFile` | A file this protocol version does not classify, including audio |
| `GTText` | A string. No sources |
| `GTNumber` | An int or float. No sources |
| `GTBool` | A bool. No sources |
| `GTNull` | Unset or empty. No sources |

A sequence is one `GTImage` with several sources rather than its own type. Handle "many
sources" from the start.

### Source kinds

| `kind` | Handling |
|---|---|
| `path` | Filesystem path. Feed to a Read node |
| `url` | HTTP(S) URL. The host fetches it; this layer moves no bytes |
| `inline` | Bytes stayed in the engine. `value` is null, `byte_count` gives the size. Read via the url or path form of the same value, or treat as unavailable |
| `macro` | Unresolved template. `value` holds raw text. Not a path, do not open. Show as a configuration error |

### Source fields

| Field | Notes |
|---|---|
| `value` | Locator, null for `inline` |
| `format` | Reported only when known, never guessed. Null on an extensionless URL. Sniff locally if certainty is required |
| `width`, `height`, `byte_count` | Null unless the engine reported them |
| `is_pattern` | True means frame padding (`####`) in the path. Correct for a Read node `file` knob, invalid for a direct file open. Check before any `fopen` |
| `raw` | Pre-resolution text, diagnostic |

`colorspace` is always null in v1. The engine's own colour field reports channel layout
(`RGB`, `RGBA`, `Grayscale`) rather than a transfer function, so it cannot express whether
pixels are sRGB or scene-linear. Nuke works scene-linear: pick a host default, make it
visible to the artist, and read the field defensively for when it starts carrying a value.

## Errors

Every failure is a typed result, never a dropped frame or a raw exception.

| Step | Detail |
|---|---|
| Detect | `type == "failure_result"` |
| Message | `payload.result.result_details.result_details[0].message`, written for display to an artist |
| Log | Include `payload.result_type` so support can identify the exact failure |
| Diagnostics | `payload.result.exception` may carry a type and message. Do not parse it |

## Transport limits

Read from the engine's `websocket_direct` implementation, as noted under
[Connecting](#connecting). No test in this repo exercises that transport.

| Limit | Consequence for the host |
|---|---|
| Fire and forget | Outbound fan-out discards send errors. No acks, no backpressure, no delivery guarantee |
| A slow reader is buffered, not dropped | Each connection has its own unbounded outbound queue drained by its own writer task, so a host that stops reading costs the engine memory rather than losing frames, and never stalls another client. Read on a dedicated thread regardless: that queue is the engine's memory, not the host's |
| No replay | No buffer, backlog, or resume cursor. A frame reaches only the connections subscribed at that instant, so subscribe before starting work |
| Topic routing is not filtering | Every subscriber to a topic gets every frame on it, and `event_topic` is shared with the editor. Filter on `request_id` and `payload_type` too |
| No auth, no TLS | Anything that can reach the port can drive the engine. The loopback bind is the only access control there is |
| No continuity across reconnects | After a drop: reconnect, re-subscribe both topics, re-issue `NukeConnectRequest`, re-read state |

`NukeGetExecutionStateRequest` is the authority whenever running state is uncertain, and
`NukeGetParameterValuesRequest` whenever a parameter's value is.

## Version compatibility

`PROTOCOL_VERSION` is a single integer, not semver.

| Change | Version bump | Effect on a host |
|---|---|---|
| New field on a request, result, or event | No | None, if unknown fields are ignored |
| New verb or notification type | No | None, if unknown `payload_type` is ignored |
| New engine artifact class mapped to an existing value type | No | None |
| New value type or source kind | Yes | Breaks; a host switches on a closed set |
| Verb, notification, field, value type, or source kind removed or renamed | Yes | Breaks; a new version is published |
| Optional field becomes required | Yes | Breaks |
