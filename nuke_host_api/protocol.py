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
"""

from __future__ import annotations

PROTOCOL_VERSION = 1

# Oldest first. A host offers the versions it knows; the highest mutual one wins.
SUPPORTED_PROTOCOL_VERSIONS = (1,)

LIBRARY_VERSION = "0.1.0"


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
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Value types. Closed set: a host switches on exactly these, forever.
class ValueType:
    """Value types a host may receive."""

    IMAGE = "GTImage"
    VIDEO = "GTVideo"
    FILE = "GTFile"
    TEXT = "GTText"
    NUMBER = "GTNumber"
    BOOLEAN = "GTBoolean"
    NULL = "GTNull"


VALUE_TYPES = (
    ValueType.IMAGE,
    ValueType.VIDEO,
    ValueType.FILE,
    ValueType.TEXT,
    ValueType.NUMBER,
    ValueType.BOOLEAN,
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
