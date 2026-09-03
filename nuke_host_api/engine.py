"""The engine side of the boundary: narrowing, plus the queries every verb repeats.

``GriptapeNodes`` is named here and nowhere above, so a handler reads as host vocabulary
in and a wording decision out. Two things the engine's API forces on every caller live
here rather than in each handler: results typed as a union that must be narrowed before
any field is read, and queries that reject a null flow name instead of defaulting to the
current context.

Deliberately not a mirror of the engine's API. A verb's own one-shot request (load, start,
cancel, set a parameter) is issued by that handler through ``request``; wrapping each one
in a method here would double the surface without hiding anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from griptape_nodes.retained_mode.events.app_events import (
    GetEngineVersionRequest,
    GetEngineVersionResultSuccess,
)
from griptape_nodes.retained_mode.events.base_events import AppEvent, AppPayload, RequestPayload, ResultPayload
from griptape_nodes.retained_mode.events.context_events import (
    GetWorkflowContextRequest,
    GetWorkflowContextSuccess,
)
from griptape_nodes.retained_mode.events.execution_events import (
    GetFlowStateRequest,
    GetFlowStateResultSuccess,
)
from griptape_nodes.retained_mode.events.flow_events import (
    GetTopLevelFlowRequest,
    GetTopLevelFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    ListAllWorkflowsRequest,
    ListAllWorkflowsResultSuccess,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes


@dataclass(frozen=True)
class Attempt[S: ResultPayload]:
    """One engine request's outcome.

    ``value`` is the narrowed success payload, or None when the engine refused.
    ``details`` carries the engine's own ``result_details`` either way, so a handler can
    quote the engine's reason inside the failure it words for a host rather than inventing
    a vaguer one.
    """

    value: S | None
    details: str


def request[S: ResultPayload](payload: RequestPayload, success: type[S]) -> Attempt[S]:
    """Issue one engine request, narrowed to the success type the caller expects.

    Every result the engine returns is typed as a union of success and failure, so without
    this each call site repeats the same isinstance narrowing and each decides separately
    what a refusal means.
    """
    result = GriptapeNodes.handle_request(payload)
    details = str(result.result_details)
    if isinstance(result, success):
        return Attempt(result, details)
    return Attempt(None, details)


def event_topic() -> str:
    """Return the topic host notifications are published on.

    Mirrors the app layer's default response topic. A host cannot derive this, so
    NukeConnectRequest hands it over.
    """
    session_id = GriptapeNodes.get_session_id()
    if session_id:
        return f"sessions/{session_id}/response"
    engine_id = GriptapeNodes.get_engine_id()
    if engine_id:
        return f"engines/{engine_id}/response"
    return "response"


def engine_version() -> str:
    """Return the engine's version, or "unknown" when it will not say."""
    attempt = request(GetEngineVersionRequest(), GetEngineVersionResultSuccess)
    if attempt.value is None:
        return "unknown"
    return f"{attempt.value.major}.{attempt.value.minor}.{attempt.value.patch}"


def top_level_flow_name() -> str | None:
    """Return the loaded top-level flow's name, or None when nothing is loaded.

    GetFlowStateRequest and CancelFlowRequest both reject a null flow_name rather than
    defaulting to the current context, so every caller has to resolve it first.
    """
    attempt = request(GetTopLevelFlowRequest(), GetTopLevelFlowResultSuccess)
    if attempt.value is None:
        return None
    return attempt.value.flow_name


def current_workflow_id() -> str:
    """Return the loaded workflow's id, or empty when none is loaded."""
    attempt = request(GetWorkflowContextRequest(), GetWorkflowContextSuccess)
    if attempt.value is None or not attempt.value.workflow_name:
        return ""
    return attempt.value.workflow_name


def workflow_table() -> dict | None:
    """Return the engine's raw workflow dict, or None if the engine refused."""
    attempt = request(ListAllWorkflowsRequest(), ListAllWorkflowsResultSuccess)
    if attempt.value is None:
        return None
    return attempt.value.workflows


def workflow_entry(workflow_id: str) -> dict | None:
    """Return one registry entry, or None when the registry is unreadable or the id is unknown.

    For callers that treat both the same. A verb that must tell a host which of the two
    happened reads ``workflow_table`` and indexes it itself.
    """
    table = workflow_table()
    entry = table.get(workflow_id) if table else None
    return entry if isinstance(entry, dict) else None


def flow_state(flow_name: str) -> Attempt[GetFlowStateResultSuccess]:
    """Read one flow's execution state."""
    return request(GetFlowStateRequest(flow_name=flow_name), GetFlowStateResultSuccess)


def flow_is_running(state: GetFlowStateResultSuccess) -> bool:
    """Report whether a flow state describes an execution in progress.

    One predicate, used by both the execute guard and the state report, so the two cannot
    disagree about what running means.
    """
    return bool(state.resolving_nodes or state.control_nodes)


def is_running() -> bool:
    """Report whether the engine is mid-execution."""
    flow_name = top_level_flow_name()
    if flow_name is None:
        return False
    attempt = flow_state(flow_name)
    if attempt.value is None:
        return False
    return flow_is_running(attempt.value)


def emit_event(payload: AppPayload) -> None:
    """Push a host notification onto the one path that actually reaches a connected host.

    ``put_event`` is what reaches IPC; ``broadcast_app_event`` only notifies in-process
    listeners, so any code emitting a notification for a host, not only ``execution_bridge``,
    goes through this rather than that.
    """
    GriptapeNodes.EventManager().put_event(AppEvent(payload=payload))
