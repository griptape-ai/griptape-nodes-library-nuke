# Browser host panel

Browser dashboard for the Nuke host API over `websocket_direct`.

```bash
make host-api/dashboard
```

Enable `websocket_direct` first; see `nuke_host_api/INTEGRATION.md` under "Connecting." The page
loads Preact and htm from unpkg. It requires no build or server and can be opened from disk.

The protocol contract is `protocol.py` and `INTEGRATION.md`, not this panel.

## What it exercises

| Step | Verbs |
| --- | --- |
| Connect and recover state | `NukeConnectRequest`, `NukeGetExecutionStateRequest` |
| Read the current project | `NukeListProjectsRequest`, `NukeGetCurrentProjectRequest` |
| Preview and switch projects | `NukeDescribeProjectRequest`, `NukeSetCurrentProjectRequest` |
| List, describe, and load workflows | `NukeListWorkflowsRequest`, `NukeDescribeWorkflowRequest`, `NukeLoadWorkflowRequest` |
| Edit parameters | `NukeSetParameterValuesRequest` |
| Run, poll, and cancel | `NukeExecuteWorkflowRequest`, `NukeCancelExecutionRequest`, `NukeGetExecutionStateRequest` || Read outputs | `NukeGetParameterValuesRequest` |

The Events drawer shows progress, node-state, and value notifications.

## Files

| File | Holds |
| --- | --- |
| `index.html` | Dependency-ordered scripts |
| `protocol.js` | Verbs, notifications, value types, and states |
| `config.js` | Reply topic, timeouts, backoff, debounce, and limits |
| `store.js` | State, render scheduling, and local preferences |
| `values.js` | Value descriptor conversion |
| `transport.js` | Socket, request correlation, message dispatch, and wire log |
| `events.js` | Notification ingestion and event feed |
| `actions.js` | Workflow, value, execution, and project requests |
| `session.js` | Connection, resync, and reconnect handling |
| `main.js` | Transport, event, action, and UI wiring |
| `ui/*` | Panel presentation |

Scripts load in dependency order from `index.html`. `main.js` wires `Transport.setHandlers` and
`Events.setEventHooks`.
