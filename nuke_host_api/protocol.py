"""The frozen surface. Everything a host binds to is named here.

Naming rule: anything the engine registers in a process-global table carries a ``Nuke``
prefix, because ``PayloadRegistry`` is keyed by bare class name and ``register`` silently
overwrites a collision. That covers payload classes and node types. Names that are only
module-scoped, like the enums below, carry no prefix because they cannot collide.

A host plugin is the slowest-moving artifact in the system: Nuke is pinned by
studios for years, and an NDK plugin is recompiled per Nuke major version. So the
plugin must hold as little knowledge as possible, and every name it does know must
live in one file that changes under an explicit versioning policy.

Versioning policy
-----------------
``PROTOCOL_VERSION`` is a single integer. It is bumped only by a breaking change.

Free (no bump):
  - Adding a field to a request, result, or event. Both sides ignore unknown fields.
  - Mapping a newly invented engine artifact class onto an existing host type.
  - Adding a new verb or event type. A host that does not know it never asks and
    never subscribes.

Bumps the version:
  - Removing or renaming a verb, event, field, host type, or source kind.
  - Changing the meaning of an existing field.

``SUPPORTED_PROTOCOL_VERSIONS`` is the support window. Studios keep old plugin
binaries in service for years, so entries leave this list on a stated schedule and
not before.

One rename happened without a version bump: ``ExecutionState``'s ``SUCCEEDED`` became
``COMPLETED``, both a rename and a meaning change, which the rule above says should bump
the version. It did not, because it happened before this protocol's first release: no
compiled plugin has ever spoken ``PROTOCOL_VERSION`` 1, so none depends on the old name.
This is a one-time exception for a value that never shipped, not a precedent. A rename
after release, of this or anything else in this file, MUST bump ``PROTOCOL_VERSION``.
"""

from __future__ import annotations

PROTOCOL_VERSION = 1

# Oldest first. A host offers the versions it knows; the highest mutual one wins.
SUPPORTED_PROTOCOL_VERSIONS = (1,)


# Verbs. A host sends these as `request_type` on the wire.
class Verb:
    """Request type names. Kept as strings because the host names them, not imports them."""

    CONNECT = "NukeConnectRequest"
    LIST_WORKFLOWS = "NukeListWorkflowsRequest"
    DESCRIBE_WORKFLOW = "NukeDescribeWorkflowRequest"
    EXECUTE_WORKFLOW = "NukeExecuteWorkflowRequest"
    GET_EXECUTION_STATE = "NukeGetExecutionStateRequest"
    CANCEL_EXECUTION = "NukeCancelExecutionRequest"


# Notifications. The engine pushes these; a host filters on `payload_type`.
class Notification:
    """Host event type names."""

    NODE_STATE = "NukeNodeStateEvent"
    PARAMETER_VALUE = "NukeParameterValueEvent"
    EXECUTION_STATE = "NukeExecutionStateEvent"
    SESSION_REVOKED = "NukeSessionRevokedEvent"


# Node lifecycle, collapsed from the engine's finer-grained execution events.
class NodeState:
    """States a host may see for a node."""

    UNRESOLVED = "unresolved"
    RUNNING = "running"
    RESOLVED = "resolved"
    FAILED = "failed"


class ExecutionState:
    """States a host may see for the engine's execution.

    Deliberately not per-execution. The engine threads no execution identifier through
    its execution events, so there is nothing to correlate a state against. Inventing an
    identifier in this layer would mean attributing events to "the execution that happened
    to start most recently", which is silently wrong as soon as anything else drives the
    engine, including the editor.

    When the engine grows an execution id, adding it to the execute-workflow result and to
    these notifications is an additive change and does not bump the protocol version. So
    there is no versioning reason to fake one now.

    ``COMPLETED`` reports only that the engine finished the flow, not that it succeeded.
    The engine's ``ControlFlowResolvedEvent`` fires on both a clean run and an errored one
    (there is no ``ControlFlowErroredEvent``, and the event carries no status field), so
    this layer has no flow-level outcome to report on the event stream and must not invent
    one. ``FAILED`` is reserved for the day the engine exposes that outcome on an event; it
    is not emitted today. A host detects an actual failure only by catching the live
    ``NukeNodeStateEvent`` with ``state="failed"`` as it is pushed.
    ``NukeGetExecutionStateRequest`` cannot recover a missed one after the fact: its result
    carries running state, active/involved nodes, and output values, never a flow-level
    outcome, because the engine exposes none. A host that drops its connection or
    subscribes late and misses that push has no way to learn, after the fact, that a run
    failed.

    ``CANCELLED`` may be followed by ``COMPLETED`` for the same run: the engine's cancel and
    error paths both end in the same completion event, and whether a host observes both for
    one run is a timing question this layer cannot settle by reading engine source. A host
    should treat the first terminal state it receives as authoritative and ignore a later
    one for the same run.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Value types. Closed set: a host switches on exactly these, forever. The ``GT`` prefix marks
# the far side of the boundary: inside a Nuke plugin everything is Nuke by default, so the
# names worth flagging are the ones carrying engine data. Matches the ``gt_*`` knob prefix the
# Griptape Annotator already writes into ``.nk`` scripts. The nouns are Nuke's, not the
# engine's: a movie is a movie, and an image sequence is an image with many sources.
class ValueType:
    """Value types a host may receive."""

    IMAGE = "GTImage"
    MOVIE = "GTMovie"
    FILE = "GTFile"
    TEXT = "GTText"
    NUMBER = "GTNumber"
    BOOL = "GTBool"
    NULL = "GTNull"


VALUE_TYPES = (
    ValueType.IMAGE,
    ValueType.MOVIE,
    ValueType.FILE,
    ValueType.TEXT,
    ValueType.NUMBER,
    ValueType.BOOL,
    ValueType.NULL,
)


# How a value's bytes are reachable. The layer never moves bytes, so it says where
# they are instead of guaranteeing a local file.
class SourceKind:
    """Locator kinds on a value descriptor's sources."""

    URL = "url"
    PATH = "path"
    INLINE = "inline"
    # A macro that could not be resolved. `value` holds the raw template. Not a path;
    # do not open it. Shows up when a {VAR} workflow variable was never substituted.
    MACRO = "macro"


SOURCE_KINDS = (SourceKind.URL, SourceKind.PATH, SourceKind.INLINE, SourceKind.MACRO)
