"""Narrow shared engine queries for host handlers."""

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
    """A narrowed success payload and the engine's result details."""

    value: S | None
    details: str


async def request[S: ResultPayload](payload: RequestPayload, success: type[S]) -> Attempt[S]:
    """Await the engine so a long request never occupies the loop the engine publishes events on."""
    result = await GriptapeNodes.ahandle_request(payload)
    details = str(result.result_details)
    if isinstance(result, success):
        return Attempt(result, details)
    return Attempt(None, details)


def event_topic() -> str:
    """Return the app layer's response topic, which hosts cannot derive."""
    active_session = session_id()
    if active_session:
        return f"sessions/{active_session}/response"
    active_engine = engine_id()
    if active_engine:
        return f"engines/{active_engine}/response"
    return "response"


async def engine_version() -> str:
    """Return the engine's version, or "unknown" when it will not say."""
    attempt = await request(GetEngineVersionRequest(), GetEngineVersionResultSuccess)
    if attempt.value is None:
        return "unknown"
    return f"{attempt.value.major}.{attempt.value.minor}.{attempt.value.patch}"


def engine_id() -> str:
    """Return the engine's own id, or empty when the engine has not set one."""
    return GriptapeNodes.get_engine_id() or ""


def session_id() -> str:
    """Return the current session's id, or empty when no session is open."""
    return GriptapeNodes.get_session_id() or ""


async def engine_name() -> str:
    """Empty is reserved for an engine name lookup failure."""
    attempt = await request(GetEngineNameRequest(), GetEngineNameResultSuccess)
    if attempt.value is None:
        return ""
    return attempt.value.engine_name


async def top_level_flow_name() -> str | None:
    """Resolve the flow name because flow-state and cancellation requests reject null names."""
    attempt = await request(GetTopLevelFlowRequest(), GetTopLevelFlowResultSuccess)
    if attempt.value is None:
        return None
    return attempt.value.flow_name


async def current_workflow_id() -> str:
    """Return the loaded workflow's id, or empty when none is loaded."""
    attempt = await request(GetWorkflowContextRequest(), GetWorkflowContextSuccess)
    if attempt.value is None or not attempt.value.workflow_name:
        return ""
    return attempt.value.workflow_name


async def workflow_table() -> dict | None:
    """Return the engine's raw workflow dict, or None if the engine refused."""
    attempt = await request(ListAllWorkflowsRequest(), ListAllWorkflowsResultSuccess)
    if attempt.value is None:
        return None
    return attempt.value.workflows


@dataclass(frozen=True)
class WorkflowLookup:
    """Distinguish an unreadable registry from an unknown ID."""

    entry: dict | None
    registry_readable: bool


async def lookup_workflow(workflow_id: str) -> WorkflowLookup:
    """Look one id up in the engine's registry, distinguishing why it was not found."""
    table = await workflow_table()
    if table is None:
        return WorkflowLookup(entry=None, registry_readable=False)
    entry = table.get(workflow_id)
    return WorkflowLookup(entry=entry if isinstance(entry, dict) else None, registry_readable=True)


async def workflow_entry(workflow_id: str) -> dict | None:
    return (await lookup_workflow(workflow_id)).entry


async def flow_state(flow_name: str) -> Attempt[GetFlowStateResultSuccess]:
    return await request(GetFlowStateRequest(flow_name=flow_name), GetFlowStateResultSuccess)


def flow_is_running(state: GetFlowStateResultSuccess) -> bool:
    return bool(state.resolving_nodes or state.control_nodes)


async def is_running() -> bool:
    flow_name = await top_level_flow_name()
    if flow_name is None:
        return False
    attempt = await flow_state(flow_name)
    if attempt.value is None:
        return False
    return flow_is_running(attempt.value)
