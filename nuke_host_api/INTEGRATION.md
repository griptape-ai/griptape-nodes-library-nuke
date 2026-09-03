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
| Verbs | `NukeConnectRequest`, `NukeListWorkflowsRequest`, `NukeDescribeWorkflowRequest`, `NukeExecuteWorkflowRequest`, `NukeGetExecutionStateRequest`, `NukeGetPortValuesRequest`, `NukeCancelExecutionRequest` |
| Notifications | `NukeNodeStateEvent`, `NukeParameterValueEvent`, `NukeExecutionStateEvent` |
| Value types | `GTImage`, `GTMovie`, `GTFile`, `GTText`, `GTNumber`, `GTBool`, `GTNull` |
| Source kinds | `path`, `url`, `inline`, `macro` |
| Port sections | `inputs`, `outputs` |
| Node states | `unresolved`, `running`, `resolved`, `failed` |
| Execution states | `running`, `completed`, `failed`, `cancelled` |

Binding rules:

| Rule | Reason |
|---|---|
| Bind to nothing outside the table above | Engine request and event types travel the same connection and change every release |
| Ignore unknown fields | Fields are added without a version bump; a strict parser breaks on a routine engine upgrade |
| Ignore unknown enum values, never treat as fatal | New value types and states may appear within a version |
| Never branch on `engine_version` or `engine_type` | Both are diagnostic only |

## Connecting

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
unversioned. Identity arrives on the wire instead. Every result envelope carries
`engine_id` and `session_id`, and `NukeConnectResultSuccess` carries the engine and library
versions.

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
        "request_type": "NukeGetPortValuesRequest",
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

This shape is derived from the envelope's own `dict()`/`from_dict()` contract
(`retained_mode/events/base_events.py`), not confirmed against a live `websocket_direct`
round trip, so treat it as the documented contract rather than a captured transcript like
every other frame here. Useful for a plugin that wants several verbs answered in one
network round trip, for example reading port values and execution state together on a
single poll tick, without paying one WebSocket message per verb.

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

Subscribe to a reply topic first, then connect. Required before anything else.

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
  "engine_version": "0.97.0",
  "library_version": "0.3.0",
  "event_topic": "sessions/50c24f4744a4463084ea3a701644993a/response",
  "value_types": ["GTImage", "GTMovie", "GTFile", "GTText", "GTNumber", "GTBool", "GTNull"]
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
| `inputs` | `list[dict]` | Port descriptors |
| `outputs` | `list[dict]` | Port descriptors. The only definition of "outputs" in this protocol |

Port descriptor fields:

| Field | Notes |
|---|---|
| `node` | Node name. Addresses inputs in `NukeExecuteWorkflowRequest` |
| `parameter` | Parameter name. Addresses inputs in `NukeExecuteWorkflowRequest` |
| `name` | Pre-joined `node.parameter` label for display |
| `type` | Always one of the seven value types |
| `default` | The workflow author's default, as a value descriptor. Initialize the knob to this |
| `tooltip` | Help text for the knob. Empty when the author wrote none |
| `settable` | False means the engine will refuse a value. Build the knob read-only |

`default` is a full value descriptor rather than a raw value, so a port's default and its
live value are the same shape and one code path renders both. A port with no author default
reports `GTNull` with no sources.

Every field is always present. A port the engine gave no metadata for reports `GTNull`, an
empty tooltip, and `settable: true` rather than omitting keys.

**`type` can be narrower at runtime.** For a port whose declared type names a media type or
a scalar, `type` and the value's `value_type` always match. For a port whose declared type
carries no media information, they can differ, and only in one direction:

| Declared type says | `type` reports | A value may arrive as |
|---|---|---|
| A media type or scalar (`ImageUrlArtifact`, `Sequence`, `int`, `bool`) | that type | the same type |
| An artifact class this version does not map (`GenericArtifact`) | `GTFile` | `GTFile`, `GTImage`, or `GTMovie` |
| A wildcard (`any`, `all`) | `GTText` | anything |

A `GenericArtifact` port holding `https://cdn.example.com/still.jpg` is genuinely an image,
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
      "type": "GTBool"
    },
    {
      "node": "End Flow",
      "parameter": "result_details",
      "name": "End Flow.result_details",
      "type": "GTText"
    },
    {
      "node": "End Flow",
      "parameter": "summary",
      "name": "End Flow.summary",
      "type": "GTText"
    }
  ]
}
```

Build host knobs from this. Control-flow ports are already removed, so every listed port
carries data.

### NukeExecuteWorkflowRequest

Returns once execution has started. Progress and the terminal state arrive as
notifications.

| Request field | Type | Default | Notes |
|---|---|---|---|
| `workflow_id` | `str` | required | From `NukeListWorkflowsRequest` |
| `inputs` | `dict[str, dict[str, Any]]` | `{}` | `{node: {parameter: value}}` keyed by describe's `node` and `parameter`. Plain JSON values |

| `NukeExecuteWorkflowResultSuccess` field | Type | Notes |
|---|---|---|
| `workflow_id` | `str` | Echoed |
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

A pair that is not a declared input port is rejected with
`"Not a declared input port of this workflow."` and never reaches the engine. Address
inputs only by the `node` and `parameter` `NukeDescribeWorkflowRequest` returned.

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

No request fields. Reports execution state only; a workflow's port values are a separate
read, `NukeGetPortValuesRequest`, because each one costs an engine round trip per port and
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

### NukeGetPortValuesRequest

The bulk value-reading path. Reads every declared start-flow or end-flow parameter's
current value in one call instead of one `GetParameterValueRequest`-per-port round trip a
host would otherwise have to issue itself. Values exist only for the loaded graph, so this
takes no `workflow_id`: it always answers for whatever `NukeExecuteWorkflowRequest` most
recently loaded.

| Request field | Type | Default | Notes |
|---|---|---|---|
| `sections` | `list[str]` | `[]` | One or more of `inputs`, `outputs`. Empty means both. An unrecognized name is refused, not silently ignored |

| `NukeGetPortValuesResultSuccess` field | Type | Notes |
|---|---|---|
| `workflow_id` | `str` | The workflow these values belong to |
| `requested_sections` | `list[str]` | The sections actually read, so a host can tell "not asked for" from "asked for, got nothing" |
| `inputs` | `dict` | `{node: {parameter: value_descriptor}}` for the start-flow side, matching describe's `inputs`. Empty when `inputs` was not requested or the workflow declares none |
| `outputs` | `dict` | Same shape, for the end-flow side, matching describe's `outputs` |
| `unavailable` | `list[dict]` | `{section, node, parameter, reason}` for declared ports the engine would not answer for. Reported, not omitted: an absent entry and an empty one mean different things to a host building a knob |

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
        "message": "Attempted to read declared port values. Failed because section(s) ['sideways'] are not recognized. Use one or more of ['inputs', 'outputs']."
      }
    ]
  }
}
```

### NukeCancelExecutionRequest

No arguments. Cancels whatever is running.

| Behaviour | Detail |
|---|---|
| Success reply | Cancellation requested only. Not confirmation that execution stopped |
| Terminal state | Arrives as `NukeExecutionStateEvent` with `state: "cancelled"` |
| Nothing running | Returns `NukeCancelExecutionResultFailure` rather than a silent no-op |

## Notifications

Pushed without a request, labelled with `event_topic`. Eight engine execution event types
collapse into these three notifications.

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
flow-level outcome, because the engine exposes none. `NukeGetPortValuesRequest` reads
values, a separate call with a separate purpose, and it carries no outcome either. A host
that drops its connection or connects late has no way to learn, after the fact, that a run
failed.

May also receive `cancelled` followed by `completed` for one run: the engine's cancel and
error paths both end in the same completion event, and whether a host observes both for a
single run is a timing question this layer cannot settle by reading engine source. Treat
the first terminal state received as authoritative and ignore a later one for the same run.

Carries no outputs by design. Outputs mean exactly one thing in this protocol: the ports
`NukeDescribeWorkflowRequest` declared. Read them with `NukeGetPortValuesRequest`.

## Value descriptors

Every value, in a notification or in `inputs`/`outputs` from `NukeGetPortValuesRequest`,
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

Verified against the transport implementation.

| Limit | Consequence for the host |
|---|---|
| Fire and forget | Outbound fan-out discards send errors. No acks, no backpressure, no delivery guarantee |
| A slow reader is buffered, not dropped | Each connection has its own unbounded outbound queue drained by its own writer task, so a host that stops reading costs the engine memory rather than losing frames, and never stalls another client. Read on a dedicated thread regardless: that queue is the engine's memory, not the host's |
| No replay | No buffer, backlog, or resume cursor. A frame reaches only the connections subscribed at that instant, so subscribe before starting work |
| Topic routing is not filtering | Every subscriber to a topic gets every frame on it, and `event_topic` is shared with the editor. Filter on `request_id` and `payload_type` too |
| No auth, no TLS | Anything that can reach the port can drive the engine. The loopback bind is the only access control there is |
| No continuity across reconnects | After a drop: reconnect, re-subscribe both topics, re-issue `NukeConnectRequest`, re-read state |

`NukeGetExecutionStateRequest` is the authority whenever running state is uncertain, and
`NukeGetPortValuesRequest` whenever a port's value is.

## Version compatibility

`PROTOCOL_VERSION` is a single integer, not semver.

| Change | Version bump | Effect on a host |
|---|---|---|
| New field on a request, result, or event | No | None, if unknown fields are ignored |
| New verb or notification type | No | None, if unknown `payload_type` is ignored |
| New engine artifact class mapped to an existing value type | No | None |
| Verb, notification, field, value type, or source kind removed or renamed | Yes | Breaks; a new version is published |
| Optional field becomes required | Yes | Breaks |
