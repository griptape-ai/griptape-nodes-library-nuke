"""Payload types owned by this library.

These are the only types a host names on the wire. They are deliberately not engine
request types: the handlers translate them into whatever the engine currently wants,
so engine churn is absorbed here rather than in the host binary.

Every type is registered with ``PayloadRegistry`` so inbound frames naming them by
class name resolve (see ``base_events._resolve_payload_type``).
"""

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

# Connect


@dataclass
@PayloadRegistry.register
class NukeConnectRequest(RequestPayload):
    """Open a session. The host offers the protocol versions it understands.

    Args:
        client_protocol_versions: Versions the host can speak. Empty means "assume
            the current one", which lets a bare connectivity check succeed.
        client_name: Free text for logs and support tickets, e.g. "Nuke 16.0v7".
    """

    client_protocol_versions: list[int] = field(default_factory=list)
    client_name: str = ""


@dataclass
@PayloadRegistry.register
class NukeConnectResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Session opened.

    Args:
        protocol_version: The agreed version. The host must use only this version's
            vocabulary for the rest of the session.
        supported_protocol_versions: The full support window, for diagnostics.
        engine_version: Informational. A host must not branch on it.
        library_version: Informational.
        event_topic: The topic notifications are published on. A host subscribes to it to
            receive them; it cannot derive the value.
        value_types: The closed value type set for this protocol version.
    """

    protocol_version: int
    supported_protocol_versions: list[int]
    engine_version: str
    library_version: str
    event_topic: str
    value_types: list[str]


@dataclass
@PayloadRegistry.register
class NukeConnectResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """No overlap between the host's versions and the support window."""

    supported_protocol_versions: list[int]


# Workflow discovery


@dataclass
@PayloadRegistry.register
class NukeListWorkflowsRequest(RequestPayload):
    """List workflows a host can execute.

    Args:
        runnable_only: When True, omit workflows with no declared input/output shape,
            which a host cannot drive.
    """

    runnable_only: bool = True


@dataclass
@PayloadRegistry.register
class NukeListWorkflowsResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Narrowed workflow list. Entries are ``{id, name, description, runnable}``."""

    workflows: list[dict[str, Any]]


@dataclass
@PayloadRegistry.register
class NukeListWorkflowsResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """The engine could not produce a workflow list."""


@dataclass
@PayloadRegistry.register
class NukeDescribeWorkflowRequest(RequestPayload):
    """Describe one workflow's host-visible surface."""

    workflow_id: str


@dataclass
@PayloadRegistry.register
class NukeDescribeWorkflowResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Host-visible description.

    ``inputs`` and ``outputs`` entries are ``{node, parameter, name, type, default,
    tooltip, settable}`` where ``type`` is always a member of ``protocol.VALUE_TYPES`` and
    ``default`` is a normalized value descriptor. ``node`` and ``parameter`` are split out
    because NukeExecuteWorkflowRequest addresses inputs by that pair.
    """

    workflow_id: str
    name: str
    description: str
    inputs: list[dict[str, Any]]
    outputs: list[dict[str, Any]]


@dataclass
@PayloadRegistry.register
class NukeDescribeWorkflowResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """No such workflow, or the engine could not describe it."""

    workflow_id: str


# Execution


@dataclass
@PayloadRegistry.register
class NukeExecuteWorkflowRequest(RequestPayload):
    """Load a workflow, apply inputs, and start it.

    Returns once execution has started. Progress and the terminal result arrive as
    notifications on ``event_topic``.

    Args:
        workflow_id: Id from NukeListWorkflowsRequest.
        inputs: ``{node_name: {parameter_name: value}}``. Values are plain JSON. Only pairs
            NukeDescribeWorkflowRequest declared as inputs are accepted; anything else is
            reported in ``rejected_inputs``.
    """

    workflow_id: str
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
@PayloadRegistry.register
class NukeExecuteWorkflowResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Execution started.

    Carries no execution identifier on purpose: the engine threads none through its execution
    events, so any identifier minted here could not be correlated with the notifications
    that follow. Adding one once the engine supports it is an additive change.

    Args:
        workflow_id: Echoed for convenience.
        state: One of ``protocol.ExecutionState``.
        applied_inputs: Inputs the engine accepted, so a host can detect a silently
            dropped input rather than wondering why the output looks wrong.
        rejected_inputs: Entries of ``{node, parameter, reason}``.
    """

    workflow_id: str
    state: str
    applied_inputs: list[dict[str, str]]
    rejected_inputs: list[dict[str, str]]


@dataclass
@PayloadRegistry.register
class NukeExecuteWorkflowResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """Execution could not be started, including when a run is already in progress."""

    workflow_id: str


@dataclass
@PayloadRegistry.register
class NukeGetExecutionStateRequest(RequestPayload):
    """Read what the engine is executing right now, and the outputs it has produced.

    The recovery path. Notifications are fire-and-forget with no replay, so a host that
    connected mid-execution or dropped its socket has permanently missed events. This reads
    current truth from the engine instead.

    Args:
        include_outputs: Read the current workflow's declared output ports. Costs one
            engine request per port, so a host polling only for liveness can turn it off.
    """

    include_outputs: bool = True


@dataclass
@PayloadRegistry.register
class NukeGetExecutionStateResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Current execution state, read straight from the engine.

    A pure translation of the engine's flow state, so it cannot drift from the engine's
    own view the way a cached copy in this layer would.

    Args:
        running: Whether anything is executing.
        active_nodes: Nodes currently being resolved.
        involved_nodes: Nodes participating in the current execution.
        workflow_id: The workflow currently loaded, or empty when none is.
        outputs: ``{node: {parameter: value_descriptor}}`` read from the engine's live
            parameter values, not from a cache in this layer. Empty when
            ``include_outputs`` was false or no workflow is loaded.
    """

    running: bool
    active_nodes: list[str]
    involved_nodes: list[str]
    workflow_id: str = ""
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
@PayloadRegistry.register
class NukeGetExecutionStateResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """The engine could not report its execution state, usually because no flow is loaded."""


@dataclass
@PayloadRegistry.register
class NukeCancelExecutionRequest(RequestPayload):
    """Ask the engine to stop what it is executing."""


@dataclass
@PayloadRegistry.register
class NukeCancelExecutionResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Cancellation requested. The terminal state arrives as a notification."""


@dataclass
@PayloadRegistry.register
class NukeCancelExecutionResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """The engine refused to cancel, usually because nothing was running."""


# Projects
#
# Workflows are registered per workspace and a project decides the workspace, so
# NukeListWorkflowsRequest and NukeDescribeWorkflowRequest always answer for whichever
# project is current. These four verbs let a host see that project and change it. Every
# result here is a narrowing of a richer engine type a host must never see:
# ProjectTemplate is a pydantic model with dozens of fields, ProjectValidationInfo and
# ProjectTemplateInfo are engine dataclasses, and ProjectInfo additionally carries parsed
# macro caches. Flattened to named primitives exactly as shape.ports narrows a parameter.


@dataclass
@PayloadRegistry.register
class NukeListProjectsRequest(RequestPayload):
    """List every project template the engine has loaded or attempted to load.

    Args:
        include_system_builtins: Whether to include the system defaults entry. False by
            default, because it is not a project a host would pick from a menu by name;
            NukeSetCurrentProjectRequest reaches it by passing ``project_id=None`` instead
            of an id this call would have to hand back.
    """

    include_system_builtins: bool = False


@dataclass
@PayloadRegistry.register
class NukeListProjectsResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Narrowed project list.

    Entries are ``{id, name, description, file_path, parent_id, current, available,
    unavailable_reason}``, folding the engine's separate ``successfully_loaded`` and
    ``failed_to_load`` lists into one the way NukeListWorkflowsRequest reports every
    workflow with a single runnable flag rather than two lists a host must merge itself.

    ``available`` is False for a template that failed to parse, and also False for one that
    parsed but whose project-adjacent config declares a ``requires_engine`` specifier this
    running engine fails. Those are two different engine mechanisms; a host disabling a menu
    entry does not need to know which one fired, so both collapse into ``available`` and a
    human-readable ``unavailable_reason``.

    ``description`` is always empty here. The engine's project listing reports validation,
    identity, and engine-compatibility per entry, but not each template's ``description``
    field; reading that would cost one additional engine request per successfully loaded
    project just to populate a display string in a list. NukeDescribeProjectRequest and
    NukeGetCurrentProjectRequest read the full template and report a real description.
    """

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
    """The current project, narrowed to what a host can act on.

    Args:
        id: Opaque, unique per engine. A legacy project with no explicit id uses its own
            canonicalized file path as this value. Feed it back to
            NukeSetCurrentProjectRequest or NukeDescribeProjectRequest; never parse or
            construct one.
        name: Display label from the template.
        description: Display text from the template. Empty when the author wrote none.
        file_path: Absolute path to the project's YAML, or empty for a project with no
            backing file, which is the system defaults project.
        base_dir: The directory this project resolves its own relative paths against.
            Diagnostic; a host does not construct paths from it.
        workspace_dir: The workspace directory the engine is actually using right now,
            read live rather than resolved from this project's id, so it is never empty,
            including when this project is the system defaults.
        validation_status: One of ``"GOOD"``, ``"FLAWED"``, ``"UNUSABLE"``, ``"MISSING"``,
            the engine's own ProjectValidationStatus spelled as a plain string. ``GOOD`` and
            ``FLAWED`` are both usable; ``UNUSABLE`` and ``MISSING`` are not.
        problems: Human-readable validation messages, for display. Empty when
            ``validation_status`` is ``"GOOD"``.
    """

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
    """No current project is set, which the engine treats as distinct from system defaults."""


@dataclass
@PayloadRegistry.register
class NukeSetCurrentProjectRequest(RequestPayload):
    """Switch the engine to a different project.

    Args:
        project_id: Id from NukeListProjectsRequest or NukeGetCurrentProjectRequest.
            ``None`` requests the system defaults, mirroring the engine's own
            SetCurrentProjectRequest exactly: there is no separate sentinel string a host
            constructs for that case, because a host must never construct a project id.
    """

    project_id: str | None = None


@dataclass
@PayloadRegistry.register
class NukeSetCurrentProjectResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """The switch completed.

    Args:
        project_id: The id actually activated, resolved from a requested ``None`` to
            whatever the engine's system-defaults id is. Opaque; do not parse or construct.
        workspace_changed: Whether the engine's active workspace directory differs from the
            one that was active immediately before this call, read live before and after the
            switch rather than resolved from either project's id, so a switch onto or off of
            the system defaults is never mistaken for a change when the workspace it shares
            with the outgoing or incoming project stayed the same. True means the engine
            re-registered every workflow against the new workspace, so every id from an
            earlier NukeListWorkflowsRequest and every port from an earlier
            NukeDescribeWorkflowRequest is stale and must be re-read.

    Always reconnect after a successful switch, whatever ``workspace_changed`` says. Beyond
    re-registering workflows on a workspace change, the engine separately reloads every
    library, this one included, whenever the target project's library-affecting config
    (which libraries to register or download, the required engine version, or the resolved
    libraries directory) differs from the outgoing project's, and that decision is made
    independently of whether the workspace directory changed: a switch can reload every
    library while its workspace stays the same, or leave every library untouched while its
    workspace changes. The engine's own SetCurrentProjectRequest exposes no field for that
    decision, so ``workspace_changed`` cannot stand in for it and this layer cannot say
    after the fact whether a reload happened.

    A library reload tears down this library's request handlers and its outbound event
    bridge and rebuilds both (``before_library_unregistered`` in
    ``nuke_nodes/nuke_library_advanced.py``), so a host that keeps talking on its old
    connection without reconnecting may find every notification has silently stopped. This
    very reply is unaffected: the engine performs the reload synchronously while handling
    this request, before the reply is built, so nothing about a reload prevents this result
    from reaching the host. Send NukeConnectRequest again immediately after reading this
    result, then re-run NukeListWorkflowsRequest and NukeDescribeWorkflowRequest for
    anything the host plans to run next.

    If the target project's workspace does not configure this library at all, the reload
    removes this library's verbs entirely, and every request after that, including the
    reconnect, fails at the engine's own dispatch layer with an error this layer never
    shaped, because it no longer owns the verb table to shape one.
    """

    project_id: str
    workspace_changed: bool


@dataclass
@PayloadRegistry.register
class NukeSetCurrentProjectResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """The switch was refused or failed. The engine leaves the previously active project active."""


@dataclass
@PayloadRegistry.register
class NukeDescribeProjectRequest(RequestPayload):
    """Preview a project's workspace and validation before activating it.

    Args:
        project_id: Id from NukeListProjectsRequest.
    """

    project_id: str


@dataclass
@PayloadRegistry.register
class NukeDescribeProjectResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Where a project's renders would land and whether its template is usable, without switching to it.

    Args:
        project_id: Echoed.
        name: Display label from the template.
        description: Display text from the template. Empty when the author wrote none.
        workspace_dir: The workspace directory this project would resolve to if activated,
            or empty when the id resolves to no readable project file.
        validation_status: One of ``"GOOD"``, ``"FLAWED"``, ``"UNUSABLE"``, ``"MISSING"``.
        problems: Human-readable validation messages, for display.
    """

    project_id: str
    name: str
    description: str
    workspace_dir: str
    validation_status: str
    problems: list[str] = field(default_factory=list)


@dataclass
@PayloadRegistry.register
class NukeDescribeProjectResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """No template is cached for that id, so there is nothing to describe."""

    project_id: str


# Notifications
#
# Pushed to event_topic, wrapped in an AppEvent. A host filters on payload_type.


@dataclass
@PayloadRegistry.register
class NukeNodeStateEvent(AppPayload):
    """A node changed state.

    Collapsed from the engine's finer-grained execution events, so a host tracks four
    states instead of eight event types.

    Args:
        node_name: The node.
        state: One of ``protocol.NodeState``.
        detail: Error text when state is failed, otherwise empty.
    """

    node_name: str
    state: str
    detail: str = ""


@dataclass
@PayloadRegistry.register
class NukeParameterValueEvent(AppPayload):
    """A parameter value changed.

    The value is a normalized descriptor, not a raw engine value, so a host never
    sees an artifact class name or has to guess whether a string is a path.

    Args:
        node_name: The node.
        parameter_name: The parameter.
        value: A descriptor from ``value_types.normalize_value``.
    """

    node_name: str
    parameter_name: str
    value: dict[str, Any]


@dataclass
@PayloadRegistry.register
class NukeExecutionStateEvent(AppPayload):
    """Execution reached a terminal state.

    Carries no outputs, deliberately. "Outputs" has exactly one meaning in this protocol:
    the ports ``NukeDescribeWorkflowRequest`` declared. The engine's terminal event
    reports values for whichever node control flow happened to end on, which is often not
    a declared output node, so putting them here would give one field two meanings.

    A host reads outputs with ``NukeGetExecutionStateRequest``, which is the same call it
    needs after a reconnect. One code path, always matching what describe promised.

    Keeping this callback free of engine requests also honours the engine's instruction
    that execution event listeners stay cheap and non-blocking.

    Args:
        state: One of ``protocol.ExecutionState``.
        terminal_node: The node the engine finished on. Diagnostic; not a declared output.
        detail: Human-readable reason.
    """

    state: str
    terminal_node: str = ""
    detail: str = ""
