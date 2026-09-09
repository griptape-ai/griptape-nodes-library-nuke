"""Host protocol names and compatibility rules."""

from __future__ import annotations

PROTOCOL_VERSION = 1

# Oldest first; negotiation selects the highest mutual version.
SUPPORTED_PROTOCOL_VERSIONS = (1,)


class Verb:
    """Wire request type names."""

    CONNECT = "NukeConnectRequest"
    LIST_WORKFLOWS = "NukeListWorkflowsRequest"
    DESCRIBE_WORKFLOW = "NukeDescribeWorkflowRequest"
    LOAD_WORKFLOW = "NukeLoadWorkflowRequest"
    EXECUTE_WORKFLOW = "NukeExecuteWorkflowRequest"
    GET_EXECUTION_STATE = "NukeGetExecutionStateRequest"
    GET_PARAMETER_VALUES = "NukeGetParameterValuesRequest"
    SET_PARAMETER_VALUES = "NukeSetParameterValuesRequest"
    CANCEL_EXECUTION = "NukeCancelExecutionRequest"
    LIST_PROJECTS = "NukeListProjectsRequest"
    GET_CURRENT_PROJECT = "NukeGetCurrentProjectRequest"
    SET_CURRENT_PROJECT = "NukeSetCurrentProjectRequest"
    DESCRIBE_PROJECT = "NukeDescribeProjectRequest"


class Notification:
    NODE_STATE = "NukeNodeStateEvent"
    PARAMETER_VALUE = "NukeParameterValueEvent"
    EXECUTION_STATE = "NukeExecutionStateEvent"
    EXECUTION_NODES = "NukeExecutionNodesEvent"


class NodeState:
    UNRESOLVED = "unresolved"
    RUNNING = "running"
    RESOLVED = "resolved"
    FAILED = "failed"


class ParameterSection:
    INPUTS = "inputs"
    OUTPUTS = "outputs"


PARAMETER_SECTIONS = (ParameterSection.INPUTS, ParameterSection.OUTPUTS)


class ExecutionState:
    """``COMPLETED`` has no success meaning, and ``FAILED`` is reserved because the engine exposes no flow outcome."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Image sequences use multiple sources rather than a separate value type.
class ValueType:
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


class SourceKind:
    URL = "url"
    PATH = "path"
    INLINE = "inline"
    # Reserved for unresolved `{VAR}` macros. `value` is the raw template, not an openable path.
    MACRO = "macro"


SOURCE_KINDS = (SourceKind.URL, SourceKind.PATH, SourceKind.INLINE, SourceKind.MACRO)
