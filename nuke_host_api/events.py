from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from griptape_nodes.retained_mode.events.base_events import (
    AppPayload,
    RequestPayload,
    ResultPayloadFailure,
    ResultPayloadSuccess,
    WorkflowNotAlteredMixin,
)
from griptape_nodes.retained_mode.events.payload_registry import PayloadRegistry


@dataclass
@PayloadRegistry.register
class NukeConnectRequest(RequestPayload):
    client_protocol_versions: list[int] = field(default_factory=list)
    client_name: str = ""


@dataclass
@PayloadRegistry.register
class NukeConnectResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """The result envelope does not guarantee engine or session identity fields."""

    protocol_version: int
    supported_protocol_versions: list[int]
    engine_version: str
    library_version: str
    event_topic: str
    value_types: list[str]
    engine_id: str = ""
    session_id: str = ""
    engine_name: str = ""


@dataclass
@PayloadRegistry.register
class NukeConnectResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    supported_protocol_versions: list[int]


@dataclass
@PayloadRegistry.register
class NukeListWorkflowsRequest(RequestPayload):
    runnable_only: bool = True


@dataclass
@PayloadRegistry.register
class NukeListWorkflowsResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    workflows: list[dict[str, Any]]


@dataclass
@PayloadRegistry.register
class NukeListWorkflowsResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """The engine could not produce a workflow list."""


@dataclass
@PayloadRegistry.register
class NukeDescribeWorkflowRequest(RequestPayload):
    workflow_id: str


@dataclass
@PayloadRegistry.register
class NukeDescribeWorkflowResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    workflow_id: str
    name: str
    description: str
    inputs: list[dict[str, Any]]
    outputs: list[dict[str, Any]]


@dataclass
@PayloadRegistry.register
class NukeDescribeWorkflowResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    workflow_id: str


@dataclass
@PayloadRegistry.register
class NukeLoadWorkflowRequest(RequestPayload):
    """Loading clears the current graph before the replacement is known to be valid."""

    workflow_id: str = ""
    file_path: str = ""


@dataclass
@PayloadRegistry.register
class NukeLoadWorkflowResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Declarations and current values have different lifetimes."""

    workflow_id: str
    name: str
    description: str
    inputs: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    input_values: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_values: dict[str, dict[str, Any]] = field(default_factory=dict)
    unavailable: list[dict[str, str]] = field(default_factory=list)


@dataclass
@PayloadRegistry.register
class NukeLoadWorkflowResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """``engine_state_cleared`` indicates that the previous graph did not survive."""

    workflow_id: str = ""
    engine_state_cleared: bool = False


@dataclass
@PayloadRegistry.register
class NukeExecuteWorkflowRequest(RequestPayload):
    """Starts the loaded workflow without loading or replacing it."""

    workflow_id: str = ""
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
@PayloadRegistry.register
class NukeExecuteWorkflowResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """No execution ID is available because engine events carry none."""

    workflow_id: str
    state: str
    applied_inputs: list[dict[str, str]]
    rejected_inputs: list[dict[str, str]]


@dataclass
@PayloadRegistry.register
class NukeExecuteWorkflowResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    workflow_id: str = ""


@dataclass
@PayloadRegistry.register
class NukeGetExecutionStateRequest(RequestPayload):
    """Reads live state because notifications are not replayed."""


@dataclass
@PayloadRegistry.register
class NukeGetExecutionStateResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    running: bool
    active_nodes: list[str]
    involved_nodes: list[str]
    workflow_id: str = ""


@dataclass
@PayloadRegistry.register
class NukeGetExecutionStateResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """The engine could not report its execution state, usually because no flow is loaded."""


@dataclass
@PayloadRegistry.register
class NukeGetParameterValuesRequest(RequestPayload):
    sections: list[str] = field(default_factory=list)


@dataclass
@PayloadRegistry.register
class NukeGetParameterValuesResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Unavailable parameters remain distinct from empty values."""

    workflow_id: str
    requested_sections: list[str]
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    unavailable: list[dict[str, str]] = field(default_factory=list)


@dataclass
@PayloadRegistry.register
class NukeGetParameterValuesResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """No workflow is loaded, or a requested section name is not in ``protocol.PARAMETER_SECTIONS``."""


@dataclass
@PayloadRegistry.register
class NukeSetParameterValuesRequest(RequestPayload):
    """Writes are refused during execution because the engine does not expose parameter-read timing."""

    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
@PayloadRegistry.register
class NukeSetParameterValuesResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    workflow_id: str
    applied_inputs: list[dict[str, str]]
    rejected_inputs: list[dict[str, str]]


@dataclass
@PayloadRegistry.register
class NukeSetParameterValuesResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    workflow_id: str = ""


@dataclass
@PayloadRegistry.register
class NukeCancelExecutionRequest(RequestPayload):
    """Ask the engine to stop what it is executing."""


@dataclass
@PayloadRegistry.register
class NukeCancelExecutionResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Success means cancellation was requested, not completed."""


@dataclass
@PayloadRegistry.register
class NukeCancelExecutionResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """The engine refused to cancel, usually because nothing was running."""


@dataclass
@PayloadRegistry.register
class NukeListProjectsRequest(RequestPayload):
    """``None`` selects the system defaults because the engine exposes no project ID for them."""

    include_system_builtins: bool = False


@dataclass
@PayloadRegistry.register
class NukeListProjectsResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Project descriptions require per-project reads and are empty in this list."""

    projects: list[dict[str, Any]]


@dataclass
@PayloadRegistry.register
class NukeListProjectsResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """The engine could not produce a project list."""


@dataclass
@PayloadRegistry.register
class NukeGetCurrentProjectRequest(RequestPayload):
    """Get the project the engine is currently on."""


@dataclass
@PayloadRegistry.register
class NukeGetCurrentProjectResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Project IDs are opaque and may be canonical file paths for legacy projects."""

    id: str
    name: str
    description: str
    file_path: str
    base_dir: str
    workspace_dir: str
    validation_status: str
    problems: list[str] = field(default_factory=list)


@dataclass
@PayloadRegistry.register
class NukeGetCurrentProjectResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """No current project differs from the system defaults project."""


@dataclass
@PayloadRegistry.register
class NukeSetCurrentProjectRequest(RequestPayload):
    """``None`` is the engine's reserved value for the system defaults project."""

    project_id: str | None = None


@dataclass
@PayloadRegistry.register
class NukeSetCurrentProjectResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Reconnect after every successful switch because the engine does not report whether libraries reloaded."""

    project_id: str
    workspace_changed: bool


@dataclass
@PayloadRegistry.register
class NukeSetCurrentProjectResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """The switch was refused or failed. The engine leaves the previously active project active."""


@dataclass
@PayloadRegistry.register
class NukeDescribeProjectRequest(RequestPayload):
    project_id: str


@dataclass
@PayloadRegistry.register
class NukeDescribeProjectResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    project_id: str
    name: str
    description: str
    workspace_dir: str
    validation_status: str
    problems: list[str] = field(default_factory=list)


@dataclass
@PayloadRegistry.register
class NukeDescribeProjectResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    project_id: str


@dataclass
@PayloadRegistry.register
class NukeNodeStateEvent(AppPayload):
    node_name: str
    state: str
    detail: str = ""


@dataclass
@PayloadRegistry.register
class NukeParameterValueEvent(AppPayload):
    node_name: str
    parameter_name: str
    value: dict[str, Any]


@dataclass
@PayloadRegistry.register
class NukeExecutionNodesEvent(AppPayload):
    """Subflow events are not identifiable, and an empty list marks top-level completion."""

    involved_nodes: list[str]


@dataclass
@PayloadRegistry.register
class NukeExecutionStateEvent(AppPayload):
    """Terminal engine events do not expose declared outputs or execution success."""

    state: str
    terminal_node: str = ""
    detail: str = ""
