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


# Loading


@dataclass
@PayloadRegistry.register
class NukeLoadWorkflowRequest(RequestPayload):
    """Load a workflow into the engine and read back everything a host needs to drive it.

    The only verb that changes which workflow is loaded, and the only one a host must call
    before ``NukeExecuteWorkflowRequest``, ``NukeGetParameterValuesRequest``, or
    ``NukeGetExecutionStateRequest`` can answer for the workflow it means.

    Destructive on purpose, and worth a confirmation in a host's UI: the engine clears all
    object state to load a graph, so this discards whatever was loaded before, including a
    graph an editor user has open on the same engine.

    Args:
        workflow_id: Id from NukeListWorkflowsRequest. Mutually exclusive with file_path.
        file_path: Absolute path to a workflow file the engine has not registered yet. It is
            imported, registered, and then loaded, so a host can hand over a file an artist
            picked without a separate registration step. Mutually exclusive with workflow_id.
    """

    workflow_id: str = ""
    file_path: str = ""


@dataclass
@PayloadRegistry.register
class NukeLoadWorkflowResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """The workflow is loaded, described, and read back in one reply.

    Four fields rather than two, because a parameter's declaration and its current value are
    different questions with different lifetimes, and no field in this protocol carries two
    meanings. Both shapes are ones a host already parses: ``inputs`` and ``outputs`` are
    exactly ``NukeDescribeWorkflowResultSuccess``'s lists, and ``input_values`` and
    ``output_values`` are exactly ``NukeGetParameterValuesResultSuccess``'s maps. A host that
    reads both of those verbs today needs no new parsing for this one.

    Args:
        workflow_id: The loaded workflow's id. Resolved from ``file_path`` when that was
            what the host sent, so this is how a host learns the id to use afterwards.
        name: Display label.
        description: Author's description, empty when there is none.
        inputs: Declared start-flow parameter descriptors. Build knobs from these.
        outputs: Declared end-flow parameter descriptors.
        input_values: ``{node: {parameter: value_descriptor}}`` for the start-flow side.
            Initialize knobs to these rather than to a descriptor's ``default``, which is the
            author's value and not what the graph currently holds.
        output_values: Same shape, for the end-flow side. Populated for a workflow that has
            run before; empty descriptors for one that has not.
        unavailable: Declared parameters the engine would not read, as
            ``{section, node, parameter, reason}``. Reported rather than omitted, for the same
            reason as on NukeGetParameterValuesRequest: an absent entry and an empty one mean
            different things to a host building a knob.
    """

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
    """Nothing was loaded, and whatever was loaded before is untouched.

    Covers an ambiguous or empty request, an unknown id, a file the engine could not import,
    a workflow the engine could not load, and a run already in progress.

    Args:
        workflow_id: The id asked for, or the one resolved from ``file_path``. Empty when the
            request never got far enough to name one.
    """

    workflow_id: str = ""


# Execution


@dataclass
@PayloadRegistry.register
class NukeExecuteWorkflowRequest(RequestPayload):
    """Apply inputs to the loaded workflow and start it.

    Loads nothing. A host loads with ``NukeLoadWorkflowRequest`` and starts with this, so
    starting a run costs one engine round trip per input plus one to start, and never a
    clear-and-reload of the graph the host just set up.

    Returns once execution has started. Progress and the terminal result arrive as
    notifications on ``event_topic``.

    Args:
        workflow_id: Optional. When set, it must be the workflow already loaded, and the
            request is refused if it is not. Empty runs whatever is loaded. Send it if the
            host tracks what it loaded, which turns a graph swapped out from under it, by an
            editor user or another tool, into a refusal instead of a run of the wrong
            workflow.
        inputs: ``{node_name: {parameter_name: value}}``. Values are plain JSON. Only pairs
            NukeDescribeWorkflowRequest declared as inputs are accepted; anything else is
            reported in ``rejected_inputs``.
    """

    workflow_id: str = ""
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
@PayloadRegistry.register
class NukeExecuteWorkflowResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Execution started.

    Carries no execution identifier on purpose: the engine threads none through its execution
    events, so any identifier minted here could not be correlated with the notifications
    that follow. Adding one once the engine supports it is an additive change.

    Args:
        workflow_id: The workflow that ran. Always the loaded workflow's id, so a host that
            sent none still learns which workflow it started.
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
    """Execution could not be started.

    Covers a run already in progress, nothing loaded to run, and a ``workflow_id`` naming a
    workflow other than the loaded one.
    """

    workflow_id: str = ""


@dataclass
@PayloadRegistry.register
class NukeGetExecutionStateRequest(RequestPayload):
    """Read what the engine is executing right now.

    The recovery path for running state. Notifications are fire-and-forget with no replay,
    so a host that connected mid-execution or dropped its socket has permanently missed
    events. This reads current truth from the engine instead.

    Reports execution state only. A workflow's current parameter values are a separate
    question with a separate cost (one engine read per parameter), so they are read with
    ``NukeGetParameterValuesRequest`` instead of being folded in here. One verb, one meaning.
    """


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
    """

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
    """Read every declared parameter's current value, selectable by side.

    The bulk-read path: a host that wants every start-flow parameter, or every end-flow
    parameter, reads them in one call instead of issuing one ``GetParameterValueRequest``
    per parameter itself. ``NukeDescribeWorkflowRequest`` already told a host which parameters exist;
    this reads what they currently hold.

    Values exist only for the loaded graph, so this takes no ``workflow_id``: it always
    answers for whatever ``NukeLoadWorkflowRequest`` most recently loaded, the same workflow
    ``NukeGetExecutionStateResultSuccess.workflow_id`` names. Load already returns these
    values once, so this is the verb for reading them *again*: after a run finishes, or after
    a reconnect that missed every notification.

    Args:
        sections: Which of ``protocol.PARAMETER_SECTIONS`` to read. Empty means every section,
            which lets a host that wants both sides skip spelling them out. An unknown
            name is refused rather than silently answering for nothing.
    """

    sections: list[str] = field(default_factory=list)


@dataclass
@PayloadRegistry.register
class NukeGetParameterValuesResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Every requested section's parameter values, read live from the engine.

    Args:
        workflow_id: The workflow these values belong to. Echoed so a host that reads this
            after a reconnect can confirm it matches what it expected.
        requested_sections: The sections actually read, so a host can tell a section it did
            not ask for from a section it asked for and got nothing back.
        inputs: ``{node: {parameter: value_descriptor}}`` for the start-flow side. Empty
            when ``inputs`` was not requested or the workflow declares none.
        outputs: Same shape, for the end-flow side. The only definition of "outputs" in
            this protocol, matching ``NukeDescribeWorkflowResultSuccess.outputs``.
        unavailable: Declared parameters the engine would not answer for, as
            ``{section, node, parameter, reason}``. Reported rather than silently omitted,
            because a missing entry and an empty one mean different things to a host
            building a knob: one is unset, the other could not be read at all.
    """

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
    the parameters ``NukeDescribeWorkflowRequest`` declared. The engine's terminal event
    reports values for whichever node control flow happened to end on, which is often not
    a declared output node, so putting them here would give one field two meanings.

    A host reads outputs with ``NukeGetParameterValuesRequest``, which is the same call it
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
