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

# Session
#
# One client owns this engine at a time (see ``session.py``). Every verb but
# NukeConnectRequest carries the token connect handed back, and is refused without one.


@dataclass
class NukeSessionScopedRequest:
    """Mixin giving a host verb the token that proves its caller holds the connect lease.

    Mixed into every request except ``NukeConnectRequest``, which is how a host gets a
    token in the first place and so cannot be asked to already have one. ``session_token``
    is declared keyword-only on this mixin specifically so it can be combined with a
    concrete request's own required, non-default fields (e.g. ``NukeDescribeWorkflowRequest.
    workflow_id``) without violating dataclass field-ordering rules: a keyword-only field is
    exempt from the "no required field after a defaulted one" check that would otherwise fire
    wherever this mixin sits in a subclass's base list.

    Defaults to empty rather than being required, so a host that has not connected yet still
    structures off the wire cleanly and receives the library's own worded refusal instead of
    a raw deserialization error.

    ``omit_from_result`` in the field metadata is load-bearing, not decorative. The engine's
    ``EventManager`` echoes the originating request back inside every reply envelope
    (``EventResultSuccess``/``EventResultFailure``), and that envelope is published to
    ``event_topic`` when a host sends no ``response_topic`` of its own -- the same topic the
    editor and every other library read (see ``NukeConnectResultSuccess.event_topic``,
    ``NukeSessionRevokedEvent``). Without this metadata the bearer token this whole session
    design rests on would ride back out on that shared topic on every single request, which is
    exactly the exposure ``NukeSessionRevokedEvent`` was written to avoid by carrying
    ``revoked_client_id`` instead of a token. ``EventManager._handle_request_core`` nulls any
    field so marked before building the result, matching ``static_file_events.content``.
    """

    session_token: str = field(default="", kw_only=True, metadata={"omit_from_result": True})


@dataclass
@PayloadRegistry.register
class NukeSessionExpiredResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """This host's session token was missing, unknown, or superseded by a takeover.

    Returned for *any* verb but connect, in place of that verb's own ``ResultFailure``, so a
    host can recognize "reconnect and retry" as one shape regardless of which request it was
    making when its lease lapsed. Checked in ``dispatch.verb``, the one place every routed
    verb already funnels through, so no individual handler has to know about sessions at all.
    """


# Connect


@dataclass
@PayloadRegistry.register
class NukeConnectRequest(RequestPayload):
    """Open a session. The host offers the protocol versions it understands.

    Args:
        client_protocol_versions: Versions the host can speak. Empty means "assume
            the current one", which lets a bare connectivity check succeed.
        client_name: Free text for logs and support tickets, e.g. "Nuke 16.0v7".
        client_id: A stable id identifying this Nuke session, distinct from client_name.
            Minted once (e.g. a uuid4 generated when the plugin loads) and reused across
            every reconnect that session makes, so a crash or a plugin reload can claim its
            own lease back without ``force``. Required: an empty value is refused, because
            an unnamed claimant makes exclusivity meaningless.
        force: Take the engine over even if a different, live client_id currently holds it.
            Revokes that client's session; see NukeSessionRevokedEvent.
    """

    client_protocol_versions: list[int] = field(default_factory=list)
    client_name: str = ""
    client_id: str = ""
    force: bool = False


@dataclass
@PayloadRegistry.register
class NukeConnectResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Session opened, and this engine's lease now belongs to this client_id.

    Args:
        protocol_version: The agreed version. The host must use only this version's
            vocabulary for the rest of the session.
        supported_protocol_versions: The full support window, for diagnostics.
        engine_version: Informational. A host must not branch on it.
        library_version: Informational.
        event_topic: The topic notifications are published on. A host subscribes to it to
            receive them; it cannot derive the value.
        value_types: The closed value type set for this protocol version.
        session_token: Carry this on every other request. A request sent without it, or
            with one a later takeover superseded, is refused with
            NukeSessionExpiredResultFailure regardless of what that request was asking for.
    """

    protocol_version: int
    supported_protocol_versions: list[int]
    engine_version: str
    library_version: str
    event_topic: str
    value_types: list[str]
    session_token: str


@dataclass
@PayloadRegistry.register
class NukeConnectResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """No overlap between the host's versions and the support window, no client_id was given,
    or a different, live client_id already holds this engine's lease.

    Args:
        supported_protocol_versions: The full support window, for diagnostics.
        holder_client_name: The client_name of the session presently holding the engine,
            set only for a lease refusal. Never its client_id or session_token: a rejected
            client must not be handed enough to impersonate the one it lost to.
        holder_idle_seconds: How long the holder has gone quiet, set only for a lease
            refusal, so a host can judge whether ``force=true`` is warranted.
    """

    supported_protocol_versions: list[int]
    holder_client_name: str = ""
    holder_idle_seconds: float = 0.0


# Workflow discovery


@dataclass
@PayloadRegistry.register
class NukeListWorkflowsRequest(NukeSessionScopedRequest, RequestPayload):
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
class NukeDescribeWorkflowRequest(NukeSessionScopedRequest, RequestPayload):
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
class NukeExecuteWorkflowRequest(NukeSessionScopedRequest, RequestPayload):
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
class NukeGetExecutionStateRequest(NukeSessionScopedRequest, RequestPayload):
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
class NukeCancelExecutionRequest(NukeSessionScopedRequest, RequestPayload):
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


@dataclass
@PayloadRegistry.register
class NukeSessionRevokedEvent(AppPayload):
    """This engine's lease was taken from one client_id and handed to another.

    Pushed on both a forced takeover and an automatic stale one; ``reason`` says which.
    Best effort, like every notification: the transport drops send errors on the floor and
    there is no replay, so a revoked client that misses this learns the same fact, more
    reliably, the moment it next carries its now-superseded token on any other verb and
    receives NukeSessionExpiredResultFailure. This event exists for the case where that
    client is watching the stream and can react immediately rather than on its next request.

    Args:
        revoked_client_id: The client_id whose lease was just taken. Deliberately the
            *id*, not the token: event_topic is shared with the editor and every other
            library, so a token must never appear on it, but a client_id is not a secret
            and a revoked client needs it to recognize this event names its own session.
        new_holder_client_name: The client_name of whoever holds the engine now.
        reason: "forced" or "stale". Diagnostic text, not a closed protocol.ExecutionState-
            style enum, because nothing here dispatches on it.
    """

    revoked_client_id: str
    new_holder_client_name: str
    reason: str
