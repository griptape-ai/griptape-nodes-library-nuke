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

    ``engine_id``, ``session_id``, and ``engine_name`` are read from this reply rather than
    from the result envelope, which makes no compatibility promise about carrying them; see
    INTEGRATION.md.

    Args:
        protocol_version: The agreed version. The host must use only this version's
            vocabulary for the rest of the session.
        supported_protocol_versions: The full support window, for diagnostics.
        engine_version: Informational. A host must not branch on it.
        library_version: Informational.
        event_topic: The topic notifications are published on. A host subscribes to it to
            receive them; it cannot derive the value.
        value_types: The closed value type set for this protocol version.
        engine_id: The engine's own id. Empty when the engine has not set one.
        session_id: The engine's active session, or empty when no session is open. Engine
            state, shared with the editor and every other client, not this connection's own.
        engine_name: The engine's human-readable name. Empty when the engine could not
            report one.
    """

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
    graph an editor user has open on the same engine. It discards it before it knows the load
    will succeed, so a failure can leave nothing loaded at all; see
    ``NukeLoadWorkflowResultFailure.engine_state_cleared``.

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
    """Nothing was loaded. Whether the previous graph survived depends on how far the load got.

    Covers an ambiguous or empty request, an unknown id, a file the engine could not import,
    a workflow the engine could not load, and a run already in progress. Every one of those
    except the engine's own load failure is decided before the engine is touched.

    Args:
        workflow_id: The id asked for, or the one resolved from ``file_path``. Empty when the
            request never got far enough to name one.
        engine_state_cleared: True when the engine had already discarded the previous graph
            before it failed. Loading asks for a clean slate, and the engine clears all object
            state before it builds the graph, so a workflow that fails inside its own file
            leaves the engine empty. A host that keeps showing knobs for what it had loaded
            must drop them when this is set, and must ask an artist before retrying, since the
            comp they had open is already gone.
    """

    workflow_id: str = ""
    engine_state_cleared: bool = False


# Execution


@dataclass
@PayloadRegistry.register
class NukeExecuteWorkflowRequest(RequestPayload):
    """Apply inputs to the loaded workflow and start it.

    Loads nothing. A host loads with ``NukeLoadWorkflowRequest`` and starts with this, so
    starting a run costs six engine requests plus one per input forwarded to the engine, and
    never a clear-and-reload of the graph the host just set up.

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
            reported in ``rejected_inputs``. Sending inputs to a workflow that declares none,
            which includes an unsaved editor graph, is refused rather than run: none of them
            could be applied, and the run would produce plausible output from the author's
            values instead of the host's. Send none to run a graph as it stands.
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
        rejected_inputs: Entries of ``{node, parameter, reason}``. A rejection is either the
            host's own to fix or the engine's, and the split is whether the input was forwarded
            at all. Two are turned away first: a ``node`` whose value is not an object of
            parameters, reported with ``parameter`` as ``"*"`` since no single parameter was
            named, and a pair that is not a declared input. Anything else is a declared pair the
            engine itself refused, carrying the engine's own reason.
    """

    workflow_id: str
    state: str
    applied_inputs: list[dict[str, str]]
    rejected_inputs: list[dict[str, str]]


@dataclass
@PayloadRegistry.register
class NukeExecuteWorkflowResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """Execution could not be started.

    Covers a run already in progress, nothing loaded to run, a ``workflow_id`` naming a
    workflow other than the loaded one, and three ways inputs can arrive with nothing to apply
    them to: a loaded graph that declares no input parameters, a registry the engine could not
    read to find out what it declares, and a loaded id that is no longer in the registry at all.
    Those three leave the same empty allow-list behind and are worded apart on purpose, because
    each is fixed differently.
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
class NukeSetParameterValuesRequest(RequestPayload):
    """Set the loaded workflow's declared input values, without starting a run.

    The write half of ``NukeGetParameterValuesRequest``, for a host that wants to stay live
    with the engine as an artist edits a knob, rather than only diverging locally until the
    next ``NukeExecuteWorkflowRequest``. Loaded-state-addressed like the read verb, so it
    takes no ``workflow_id``: a value can only be set on a node that exists, and the only
    node that exists is whatever ``NukeLoadWorkflowRequest`` most recently loaded.

    Refused while the engine is executing, for the same reason ``NukeLoadWorkflowRequest`` and
    ``NukeExecuteWorkflowRequest`` refuse mid-run: the engine's own scheduler decides when a
    node's parameter is actually read, so a value set while it is running cannot be told apart
    from one that lands before the node that consumes it or one that lands after. Answering as
    if it landed in time would be a claim this layer cannot verify. Cancel with
    ``NukeCancelExecutionRequest`` first, or wait for the run to finish, then retry.

    Args:
        inputs: ``{node_name: {parameter_name: value}}``. Values are plain JSON. The same
            shape and the same allow-list ``NukeExecuteWorkflowRequest.inputs`` uses: only
            pairs ``NukeDescribeWorkflowRequest`` declared as inputs are accepted, anything
            else is reported in ``rejected_inputs`` rather than silently dropped. A request
            with no pair to act on is refused rather than answered as a trivial success, since
            there is nothing else this request does: that covers an empty ``inputs`` and one
            where every node maps to an empty parameter dict, such as ``{"Start Flow": {}}``.
    """

    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
@PayloadRegistry.register
class NukeSetParameterValuesResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    """Values applied to the loaded graph.

    Args:
        workflow_id: The workflow the values were applied to, so a host that reads this after
            a reconnect can confirm it matches what it expected.
        applied_inputs: Entries of ``{node, parameter}`` accepted and set on the graph.
        rejected_inputs: Entries of ``{node, parameter, reason}``, worded exactly as
            ``NukeExecuteWorkflowResultSuccess.rejected_inputs`` words the same two causes: a
            pair this layer turned away itself, before any request, and a declared pair the
            engine itself refused after it was forwarded.
    """

    workflow_id: str
    applied_inputs: list[dict[str, str]]
    rejected_inputs: list[dict[str, str]]


@dataclass
@PayloadRegistry.register
class NukeSetParameterValuesResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    """Nothing was set.

    Covers an empty request, a run in progress, nothing loaded, a registry the engine could
    not read, a loaded id no longer in the registry, and a loaded graph that declares no input
    parameters. The same causes ``NukeExecuteWorkflowResultFailure`` reports, minus the ones
    that only make sense once a run has actually started.

    Args:
        workflow_id: The loaded workflow's id, or empty when none is loaded.
    """

    workflow_id: str = ""


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
class NukeExecutionNodesEvent(AppPayload):
    """The run's node set: the denominator a host pairs with NukeNodeStateEvent's numerator.

    Translates the engine's InvolvedNodesEvent, which is not one-shot and is not monotonic.
    For a serial control flow the engine reports every participating node when the run
    starts, then reports an empty list again when the run finishes; a host must snapshot
    the first non-empty list it sees as the run's total and must not read a later empty one
    as "zero nodes ran". For parallel resolution the engine builds this set as its DAG
    builder discovers work, so the set legitimately grows mid-run: a host drawing a
    fixed-size progress bar must handle the total increasing, not only nodes being checked
    off a total fixed at the first event.

    Named for the execution it reports on, alongside NukeExecutionStateEvent, rather than
    reusing the engine's own InvolvedNodesEvent class name verbatim: every other event this
    layer translates already renames or collapses the engine's vocabulary (NodeStartProcessEvent
    and four siblings become NukeNodeStateEvent's state enum; ParameterValueUpdateEvent drops
    "Update"), and carrying the engine's class name unchanged here would be the one exception.
    The field underneath keeps the engine's word regardless: it is named to match
    NukeGetExecutionStateResultSuccess.involved_nodes exactly, a tie this docstring's Args
    entry calls out on purpose, and renaming one without the other would break that parity
    instead of clarifying anything.

    Not folded into NukeExecuteWorkflowResultSuccess. That reply is written once, when the
    flow has just started and, for parallel resolution, before the engine has necessarily
    discovered the full node set; this notification is the engine's own live count and
    updates for as long as the run does. A host wanting only a one-time total for a serial
    flow still gets it, as the first event on this notification after execute returns.

    Args:
        involved_nodes: Nodes participating in the current execution, exactly as
            NukeGetExecutionStateResultSuccess.involved_nodes reports for a polled read of
            the same information.
    """

    involved_nodes: list[str]


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
