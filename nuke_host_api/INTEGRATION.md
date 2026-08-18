# Nuke host API integration reference

Wire-level reference for the host side of the protocol: a Nuke NDK plugin, a Python panel,
or any process driving a Griptape Nodes engine. Assumes this library is installed in the
engine. Every JSON frame below was captured off a live socket.

Design rationale lives in `nuke_host_api/README.md`. This document covers only what a host
sends, receives, and must handle.

## Contents

- [Bound surface](#bound-surface)
- [Setup](#setup)
- [Frame formats](#frame-formats)
- [Read loop](#read-loop)
- [Verbs](#verbs)
- [Notifications](#notifications)
- [Value descriptors](#value-descriptors)
- [Errors](#errors)
- [Transport limits](#transport-limits)
- [Version compatibility](#version-compatibility)
- [Reference client](#reference-client)

## Bound surface

Defined in `nuke_host_api/protocol.py`, pinned by
`tests/unit/fixtures/host_api/protocol_v1.json`.

| Category | Members |
|---|---|
| Verbs | `NukeConnectRequest`, `NukeListWorkflowsRequest`, `NukeDescribeWorkflowRequest`, `NukeExecuteWorkflowRequest`, `NukeGetExecutionStateRequest`, `NukeCancelExecutionRequest` |
| Notifications | `NukeNodeStateEvent`, `NukeParameterValueEvent`, `NukeExecutionStateEvent` |
| Value types | `GTImage`, `GTVideo`, `GTFile`, `GTText`, `GTNumber`, `GTBoolean`, `GTNull` |
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

## Setup

The engine's local WebSocket server is off by default. Query the driver config:

```
GetConfigValueRequest(category_and_key="ipc_drivers")
```

Require an entry with `"driver_type": "websocket_direct"` and `"enabled": true`, then read
its `host` and `port`. Default is `127.0.0.1:18125`.

```json
[
  {
    "name": "websocket_direct",
    "driver_type": "websocket_direct",
    "enabled": true,
    "host": "127.0.0.1",
    "port": 18125
  }
]
```

Connect to `ws://<host>:<port>`. Plain WebSocket, no TLS, no auth handshake.

## Frame formats

Four frame classes share one connection, discriminated by the top-level `type` field
(absent on outbound requests).

| `type` | Direction | Discriminator for dispatch |
|---|---|---|
| `subscribe`, `unsubscribe`, `ping` | host to engine | Handled by the transport, never reaches the engine |
| `pong` | engine to host | Echoes the `id` from `ping` |
| absent | host to engine | `payload.request_type` |
| `success_result`, `failure_result` | engine to host | `payload.request_id`, then `payload.result_type` |
| `app_event` | engine to host | `payload.payload_type` |

### Control frames

```json
{
  "type": "subscribe",
  "topic": "nuke/reply"
}
```

```json
{
  "type": "unsubscribe",
  "topic": "nuke/reply"
}
```

```json
{
  "type": "ping",
  "id": "probe-1"
}
```

```json
{
  "type": "pong",
  "id": "probe-1"
}
```

### Requests

`request_id` is host-generated and echoed back; any value unique per in-flight request
works. `response_topic` is where the reply is published, and the host must already be
subscribed to it.

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

`NukeClient._pump` in `scripts/nuke_host_client.py` implements this. Port that structure
rather than a request-response helper.

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
| `event_topic` | `str` | Subscribe immediately. Not derivable; without it, replies arrive and notifications silently do not |
| `value_types` | `list[str]` | Closed value type set for this version |

```json
{
  "protocol_version": 1,
  "supported_protocol_versions": [1],
  "engine_version": "0.97.0",
  "library_version": "0.3.0",
  "event_topic": "sessions/50c24f4744a4463084ea3a701644993a/response",
  "value_types": ["GTImage", "GTVideo", "GTFile", "GTText", "GTNumber", "GTBoolean", "GTNull"]
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
      "type": "GTText"
    }
  ],
  "outputs": [
    {
      "node": "End Flow",
      "parameter": "was_successful",
      "name": "End Flow.was_successful",
      "type": "GTBoolean"
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

No execution identifier exists. The engine threads none through its execution events, so
one minted here could not be correlated with the notifications that follow. One execution
at a time is the current model. An execution id would arrive as an added field, which a
tolerant parser already handles.

### NukeGetExecutionStateRequest

The output-reading and recovery path. Notifications have no replay, so a host that
connected mid-execution or dropped its socket has permanently missed events; this call returns
current truth read live from the engine, with no cache that could disagree.

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
        "value_type": "GTBoolean",
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

Pushed to `event_topic` with no request. Eight engine execution event types collapse into
these three notifications.

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
    "value_type": "GTBoolean",
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
its connection or subscribes late has no way to learn, after the fact, that a run failed.

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
| `GTVideo` | A movie file |
| `GTFile` | A file this protocol version does not classify, including audio |
| `GTText` | A string. No sources |
| `GTNumber` | An int or float. No sources |
| `GTBoolean` | A bool. No sources |
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
| No replay | No buffer, backlog, or resume cursor. Events reach only connections subscribed at that instant. Connect and subscribe before starting work |
| Explicit subscription, silent when missed | Forgetting `event_topic` looks like a working integration with no progress reporting |
| No continuity across reconnects | After a drop, re-issue `NukeConnectRequest`, re-subscribe to the returned `event_topic`, and re-read state |

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
