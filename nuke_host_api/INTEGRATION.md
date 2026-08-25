# Nuke host API integration reference

Wire-level reference for the host side of the protocol: a Nuke NDK plugin, a Python panel,
or any process driving a Griptape Nodes engine. Assumes this library is installed in the
engine. The JSON below is illustrative, not a captured transcript; field names and shapes
are authoritative, values are examples.

Design rationale lives in `nuke_host_api/README.md`. This document covers only what a host
sends, receives, and must handle.

## Contents

- [Bound surface](#bound-surface)
- [Engine discovery and setup](#engine-discovery-and-setup)
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
| Verbs | `NukeConnectRequest`, `NukeListWorkflowsRequest`, `NukeDescribeWorkflowRequest`, `NukeExecuteWorkflowRequest`, `NukeGetExecutionStateRequest`, `NukeCancelExecutionRequest` |
| Notifications | `NukeNodeStateEvent`, `NukeParameterValueEvent`, `NukeExecutionStateEvent` |
| Value types | `GTImage`, `GTMovie`, `GTFile`, `GTText`, `GTNumber`, `GTBool`, `GTNull` |
| Source kinds | `path`, `url`, `inline`, `macro` |
| Node states | `unresolved`, `running`, `resolved`, `failed` |
| Execution states | `running`, `completed`, `failed`, `cancelled` |

Binding rules:

| Rule | Reason |
|---|---|
| Bind to nothing outside the table above | Engine request and event types travel the same connection and change every release |
| Ignore unknown fields | Fields are added without a version bump; a strict parser breaks on a routine engine upgrade |
| Ignore unknown enum values, never treat as fatal | New value types and states may appear within a version |
| Never branch on `engine_version` or `engine_type` | Both are diagnostic only |

## Engine discovery and setup

Two files on disk answer "which engines exist" and "is one running", with no wire
round-trip. `$XDG_DATA_HOME` is `~/.local/share` on Linux and macOS unless overridden.

### 1. Enable the driver, once per machine

`local_socket` ships disabled. Add it to the engine config at
`$XDG_CONFIG_HOME/griptape_nodes/griptape_nodes_config.json`, then restart the engine:

```json
{
  "ipc_drivers": [
    { "name": "websocket_api", "driver_type": "websocket_api", "enabled": true },
    { "name": "local_socket", "driver_type": "local_socket", "enabled": true }
  ]
}
```

Leave `websocket_api` enabled. It is the engine's link to the hosted service, and dropping
it from the list disables it.

Do **not** try to read this config over the wire. A host has no connection yet, so
`GetConfigValueRequest` cannot answer where to connect.

### 2. Enumerate engines

Read `$XDG_DATA_HOME/griptape_nodes/engines.json`:

```json
{
  "engines": [
    { "id": "9de4b2fe-9a6e-4253-a0b9-8677f46c9a34", "name": "honest-red-ant",
      "created_at": "2026-08-24T22:02:19.397484+00:00" }
  ],
  "default_engine_id": "9de4b2fe-9a6e-4253-a0b9-8677f46c9a34"
}
```

`name` is the label to show an artist, `id` addresses the socket. Use `default_engine_id`
when the host offers no picker.

### 3. Connect, and treat the socket as the liveness check

| Platform | Path |
|---|---|
| macOS, Linux | `$XDG_DATA_HOME/griptape_nodes/ipc/<engine_id>.sock`, `AF_UNIX` stream |
| Windows | `\\.\pipe\griptape_nodes_<engine_id>` |

The path exists only while that engine is running with the driver enabled, so its presence
is the liveness test. A registry entry with no socket is an engine installed and not
running. A connection refused on a path that does exist is an engine that died without
cleaning up.

Frames are newline-delimited JSON, one object per line, both directions. No TLS, no auth
handshake: anything that can open the socket can drive the engine. The engine creates the
socket file mode `0600`, so on a single-user machine that is owner-only by construction;
treat it as the only access control there is.

`griptape_nodes_app/cli/request.py` in the app package implements steps 2 and 3. Step 1 is a
manual config edit.

### 4. Filter everything read from the socket

The server writes every outbound frame to every connected client. No server-side topic
filtering, no subscription step. A host therefore sees replies to requests the editor made,
other libraries' events, and engine chatter unrelated to it. Discard any frame whose
`request_id` is not one this host sent and whose `payload_type` does not begin with `Nuke`.

One consequence worth stating: `event_topic` on `NukeConnectResultSuccess` is
informational on this transport. There is nothing to subscribe to, so there is no way to
miss notifications by forgetting to.

## Frame formats

Three frame classes share one connection, discriminated by the top-level `type` field
(absent on outbound requests).

| `type` | Direction | Discriminator for dispatch |
|---|---|---|
| absent | host to engine | `payload.request_type` |
| `success_result`, `failure_result` | engine to host | `payload.request_id`, then `payload.result_type` |
| `app_event` | engine to host | `payload.payload_type` |

The `local_socket` driver has no control frames: no subscribe, no unsubscribe, no ping.
Everything the engine sends outbound reaches every connected client, so a host's only
responsibility is to discard what is not addressed to it.

There is no protocol-level heartbeat either. Detect a dead engine from the socket closing,
or by sending a cheap request such as `NukeGetExecutionStateRequest` with
`include_outputs: false`.

### Requests

`request_id` is host-generated and echoed back; any value unique per in-flight request
works. `response_topic` names the topic the reply is published on and the engine puts it on
the reply envelope. On this transport a host receives the reply either way, so the value
serves only as a label to filter on.

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

Results and notifications arrive interleaved on one socket. A client that reads until it
finds its reply and discards everything else drops every notification.

Required loop:

1. Read a frame.
2. If it is a notification, dispatch it and keep reading.
3. If it carries the awaited `request_id`, it is the reply.
4. Otherwise discard it.

Implement this as a pump that owns the socket, not as a request-response helper that
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
| `event_topic` | `str` | The topic notifications are labelled with. Informational on `local_socket`, where nothing needs subscribing |
| `value_types` | `list[str]` | Closed value type set for this version |

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

The output-reading and recovery path. Notifications have no replay, so a host that
connected mid-execution or dropped its socket has permanently missed events; this call returns
current truth read live from the engine, with no cache that could disagree. It is also how a
host checks whether it may start another run.

| Request field | Type | Default | Notes |
|---|---|---|---|
| `include_outputs` | `bool` | `true` | Set `false` when polling only for liveness. Each output port costs one engine read |

| `NukeGetExecutionStateResultSuccess` field | Type | Notes |
|---|---|---|
| `running` | `bool` | Whether anything is executing |
| `active_nodes` | `list[str]` | Nodes currently resolving |
| `involved_nodes` | `list[str]` | Nodes in the current execution |
| `workflow_id` | `str` | Loaded workflow, empty when none |
| `outputs` | `dict` | `{node: {parameter: value_descriptor}}`, matching describe. Empty when `include_outputs` was false or no workflow is loaded |

```json
{
  "running": false,
  "active_nodes": [],
  "involved_nodes": [],
  "workflow_id": "nuke_api_smoke",
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
one after the fact: its result carries running state, active/involved nodes, and output
values, never a flow-level outcome, because the engine exposes none. A host that drops
its connection or connects late has no way to learn, after the fact, that a run failed.

May also receive `cancelled` followed by `completed` for one run: the engine's cancel and
error paths both end in the same completion event, and whether a host observes both for a
single run is a timing question this layer cannot settle by reading engine source. Treat
the first terminal state received as authoritative and ignore a later one for the same run.

Carries no outputs by design. Outputs mean exactly one thing in this protocol: the ports
`NukeDescribeWorkflowRequest` declared. Read them with `NukeGetExecutionStateRequest`.

## Value descriptors

Every value, in a notification or in `outputs`, has this shape:

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
| Fire and forget | Outbound fan-out discards send errors. No acks, no backpressure, no delivery guarantee. A wedged or slow reader silently misses events |
| No replay | No buffer, backlog, or resume cursor. Events reach only clients connected at that instant, so connect before starting work |
| No filtering for you | Every outbound frame reaches every client. A host that does not filter will process the editor's replies as its own |
| No continuity across reconnects | After a drop, reconnect, re-issue `NukeConnectRequest`, and re-read state |

`NukeGetExecutionStateRequest` is the authority whenever state is uncertain.

## Version compatibility

`PROTOCOL_VERSION` is a single integer, not semver.

| Change | Version bump | Effect on a host |
|---|---|---|
| New field on a request, result, or event | No | None, if unknown fields are ignored |
| New verb or notification type | No | None, if unknown `payload_type` is ignored |
| New engine artifact class mapped to an existing value type | No | None |
| Verb, notification, field, value type, or source kind removed or renamed | Yes | Breaks; a new version is published |
| Optional field becomes required | Yes | Breaks |
