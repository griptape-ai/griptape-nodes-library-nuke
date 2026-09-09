# Browser host panel

A host for the Nuke host API, in a browser, driving a real engine over `websocket_direct`. Shaped
like a host rather than a list of requests with buttons on them, because the mistakes worth catching
only appear when the verbs are wired into a flow.

```bash
make host-api/dashboard     # opens index.html in a browser
```

Enable `websocket_direct` in the engine config first (`nuke_host_api/INTEGRATION.md`, "Connecting").
The page loads Preact and htm from unpkg on first open; the engine socket stays local. No build step
and no server: the files are plain scripts loaded in order by `index.html`, so double-clicking it
works.

A testing dashboard, not a second reference client: the contract is `protocol.py` and
`INTEGRATION.md`, and no part of this panel's shape is one.

## What it exercises

Every verb and notification in `nuke_host_api/protocol.py`, reached by the flow rather than by a
button per request:

| Step                                                                        | Verbs                                                                                      |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Comes up and finds the engine, then keeps finding it                        | `NukeConnectRequest`, `NukeGetExecutionStateRequest`                                       |
| Reads the project, because a project decides which workflows exist          | `NukeListProjectsRequest`, `NukeGetCurrentProjectRequest`                                  |
| Previews a project, then switches and reconnects                            | `NukeDescribeProjectRequest`, `NukeSetCurrentProjectRequest`                               |
| Lists workflows, describes the picked one, loads it deliberately            | `NukeListWorkflowsRequest`, `NukeDescribeWorkflowRequest`, `NukeLoadWorkflowRequest`       |
| Builds parameters from the declaration, writes edits through coalesced      | `NukeSetParameterValuesRequest`                                                            |
| Runs, tracks progress from events, backstops with one batched poll, cancels | `NukeExecuteWorkflowRequest`, `NukeCancelExecutionRequest`, `NukeGetExecutionStateRequest` |
| Reads outputs, on a terminal event and after a reconnect                    | `NukeGetParameterValuesRequest`                                                            |

Notifications drive progress, node state, and streamed values; the Events tab in the drawer shows
them arriving with nothing requested.

## Files

The core is what a plugin reimplements. `ui/` is presentation and is not.

| File           | Holds                                                                            |
| -------------- | -------------------------------------------------------------------------------- |
| `index.html`   | The load order, which is also the layering                                       |
| `protocol.js`  | The frozen surface: verbs, notifications, value types, node and execution states |
| `config.js`    | This host's own choices: reply topic, timeouts, backoff, debounce, limits        |
| `store.js`     | State, coalesced renders, local preferences per engine id                        |
| `values.js`    | Value descriptors: flatten, seed a field from one, what it becomes in the DAG    |
| `transport.js` | Socket, request/reply correlation, the message pump, the wire log                |
| `events.js`    | Notification ingestion and the event feed                                        |
| `actions.js`   | Verb calls: workflows, values, execution, projects, plus the local run log       |
| `session.js`   | Connect, the one resync sequence, reconnect backoff, adopting a loaded graph     |
| `main.js`      | Wires transport to ingestion to actions, then renders                            |
| `ui/*`         | Panes: project, workflow, parameters, run, outputs and history, drawer, shell    |

Read `protocol.js` first, then `session.js` for the connect sequence, then `transport.js` for the
frames. Each file is one namespace (`Protocol`, `Config`, `Store`, and so on) and starts by naming
what it takes from the ones before it. The two seams, `Transport.setHandlers` and
`Events.setEventHooks`, are wired in `main.js` so no file reaches downward.
