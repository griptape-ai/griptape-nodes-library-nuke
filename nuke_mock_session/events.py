"""Requests the library offers AI agents as MCP tools for the artist's open Nuke session.

Each request's docstring is the tool description the agent reads, so it is written for an
agent that has never used Nuke through these tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from griptape_nodes.retained_mode.events.base_events import (
    RequestPayload,
    ResultPayloadFailure,
    ResultPayloadSuccess,
    WorkflowNotAlteredMixin,
)
from griptape_nodes.retained_mode.events.payload_registry import PayloadRegistry


@dataclass
@PayloadRegistry.register
class NukeGetScriptInfoRequest(RequestPayload):
    """Describe the Nuke script the artist has open: its path, show and shot, version, frame range, fps, format, working colorspace, and whether it has unsaved changes. Call this first to orient yourself."""


@dataclass
@PayloadRegistry.register
class NukeGetScriptInfoResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    script: dict[str, Any]


@dataclass
@PayloadRegistry.register
class NukeListNodesRequest(RequestPayload):
    """List the nodes in the open Nuke script with their class, inputs, and whether they are disabled. Pass a Nuke node class such as "Write", "Read", or "Grade" to list only that class; leave it empty to list every node."""

    node_class: str = ""


@dataclass
@PayloadRegistry.register
class NukeListNodesResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    nodes: list[dict[str, Any]]


@dataclass
@PayloadRegistry.register
class NukeGetNodeRequest(RequestPayload):
    """Read one node in the open Nuke script: its class, inputs, disabled state, and every knob value. Use the exact node name from NukeListNodesRequest."""

    node_name: str


@dataclass
@PayloadRegistry.register
class NukeGetNodeResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    node: dict[str, Any]


@dataclass
@PayloadRegistry.register
class NukeGetNodeResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    pass


@dataclass
@PayloadRegistry.register
class NukeSetKnobRequest(RequestPayload):
    """Set one knob on a node in the open Nuke script, the way an artist would in the Properties panel. Use the knob name "disable" with true or false to disable or enable the node. Returns the knob's previous value so the change can be undone."""

    node_name: str
    knob: str
    value: Any


@dataclass
@PayloadRegistry.register
class NukeSetKnobResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    node_name: str
    knob: str
    previous_value: Any
    value: Any


@dataclass
@PayloadRegistry.register
class NukeSetKnobResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    pass


@dataclass
@PayloadRegistry.register
class NukeCreateNodeRequest(RequestPayload):
    """Create a node in the open Nuke script. node_class is a Nuke node class such as "Grade", "Blur", or "Write". Optionally name it, connect its first input to an existing node, and set initial knob values."""

    node_class: str
    node_name: str = ""
    input_node: str = ""
    knobs: dict[str, Any] = field(default_factory=dict)


@dataclass
@PayloadRegistry.register
class NukeCreateNodeResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    node: dict[str, Any]


@dataclass
@PayloadRegistry.register
class NukeCreateNodeResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    pass


@dataclass
@PayloadRegistry.register
class NukeSaveNewVersionRequest(RequestPayload):
    """Save the open Nuke script as the next version (v012 becomes v013), and point every Write node's output at the new version. Do this before rendering anything that will be reviewed."""


@dataclass
@PayloadRegistry.register
class NukeSaveNewVersionResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    script_path: str
    script_version: str


@dataclass
@PayloadRegistry.register
class NukeRenderRequest(RequestPayload):
    """Render a Write node in the open Nuke script and wait for it to finish. Leave first_frame and last_frame at 0 to render the Write node's own frame range. Returns the output path and frame count."""

    write_node: str
    first_frame: int = 0
    last_frame: int = 0


@dataclass
@PayloadRegistry.register
class NukeRenderResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    render: dict[str, Any]


@dataclass
@PayloadRegistry.register
class NukeRenderResultFailure(WorkflowNotAlteredMixin, ResultPayloadFailure):
    pass


@dataclass
@PayloadRegistry.register
class NukeListRendersRequest(RequestPayload):
    """List the renders made from the open Nuke script in this session, oldest first, with each one's Write node, frame range, output path, and script version."""


@dataclass
@PayloadRegistry.register
class NukeListRendersResultSuccess(WorkflowNotAlteredMixin, ResultPayloadSuccess):
    renders: list[dict[str, Any]]
