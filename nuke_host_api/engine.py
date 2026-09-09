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
    GetEngineNameRequest,
    GetEngineNameResultSuccess,
    GetEngineVersionRequest,
    GetEngineVersionResultSuccess,
)
from griptape_nodes.retained_mode.events.base_events import RequestPayload, ResultPayload
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
    active_session = session_id()
    if active_session:
        return f"sessions/{active_session}/response"
    active_engine = engine_id()
    if active_engine:
        return f"engines/{active_engine}/response"
    return "response"


def engine_version() -> str:
    """Return the engine's version, or "unknown" when it will not say."""
    attempt = request(GetEngineVersionRequest(), GetEngineVersionResultSuccess)
    if attempt.value is None:
        return "unknown"
    return f"{attempt.value.major}.{attempt.value.minor}.{attempt.value.patch}"


def engine_id() -> str:
    """Return the engine's own id, or empty when the engine has not set one."""
    return GriptapeNodes.get_engine_id() or ""


def session_id() -> str:
    """Return the current session's id, or empty when no session is open."""
    return GriptapeNodes.get_session_id() or ""


def engine_name() -> str:
    """Return the engine's human-readable name, or empty when the engine could not report one.

    Unlike ``engine_version``, a refusal here is not "unknown": the engine's own handler only
    fails on an unexpected exception reading its identity store, not on an unset name, so an
    empty string is reserved for that path and never stands in for a name the engine actually
    has.
    """
    attempt = request(GetEngineNameRequest(), GetEngineNameResultSuccess)
    if attempt.value is None:
        return ""
    return attempt.value.engine_name


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


@dataclass(frozen=True)
class WorkflowLookup:
    """One registry lookup, keeping an unreadable registry apart from an unknown id.

    Two verbs word different failures for the two, because one is worth retrying and the
    other never is. Sharing the lookup rather than the wording is what keeps them from
    drifting: a host matching on reason text would otherwise see one verb change and not
    the other.
    """

    entry: dict | None
    registry_readable: bool


def lookup_workflow(workflow_id: str) -> WorkflowLookup:
    """Look one id up in the engine's registry, distinguishing why it was not found."""
    table = workflow_table()
    if table is None:
        return WorkflowLookup(entry=None, registry_readable=False)
    entry = table.get(workflow_id)
    return WorkflowLookup(entry=entry if isinstance(entry, dict) else None, registry_readable=True)


def workflow_entry(workflow_id: str) -> dict | None:
    """Return one registry entry, or None when the registry is unreadable or the id is unknown.

    For callers that treat both the same. A verb that must tell a host which of the two
    happened reads ``lookup_workflow``.
    """
    return lookup_workflow(workflow_id).entry


def flow_state(flow_name: str) -> Attempt[GetFlowStateResultSuccess]:
    return request(GetFlowStateRequest(flow_name=flow_name), GetFlowStateResultSuccess)


def flow_is_running(state: GetFlowStateResultSuccess) -> bool:
    """Report whether a flow state describes an execution in progress.

    One predicate, used by both the execute guard and the state report, so the two cannot
    disagree about what running means.
    """
    return bool(state.resolving_nodes or state.control_nodes)


def is_running() -> bool:
    flow_name = top_level_flow_name()
    if flow_name is None:
        return False
    attempt = flow_state(flow_name)
    if attempt.value is None:
        return False
    return flow_is_running(attempt.value)
