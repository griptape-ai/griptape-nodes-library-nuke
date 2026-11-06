from __future__ import annotations

from typing import TYPE_CHECKING

from griptape_nodes.node_library.advanced_node_library import MCPTool

from nuke_mock_session.events import (
    NukeCreateNodeRequest,
    NukeCreateNodeResultFailure,
    NukeCreateNodeResultSuccess,
    NukeGetNodeRequest,
    NukeGetNodeResultFailure,
    NukeGetNodeResultSuccess,
    NukeGetScriptInfoRequest,
    NukeGetScriptInfoResultSuccess,
    NukeListNodesRequest,
    NukeListNodesResultSuccess,
    NukeListRendersRequest,
    NukeListRendersResultSuccess,
    NukeRenderRequest,
    NukeRenderResultFailure,
    NukeRenderResultSuccess,
    NukeSaveNewVersionRequest,
    NukeSaveNewVersionResultSuccess,
    NukeSetKnobRequest,
    NukeSetKnobResultFailure,
    NukeSetKnobResultSuccess,
)
from nuke_mock_session.session import current_session

if TYPE_CHECKING:
    from collections.abc import Callable

    from griptape_nodes.retained_mode.events.base_events import RequestPayload, ResultPayload


def handle_get_script_info(request: NukeGetScriptInfoRequest) -> NukeGetScriptInfoResultSuccess:  # noqa: ARG001
    script = current_session().script_info()
    return NukeGetScriptInfoResultSuccess(script=script, result_details=f"Read {script['script_path']}.")


def handle_list_nodes(request: NukeListNodesRequest) -> NukeListNodesResultSuccess:
    nodes = current_session().list_nodes(request.node_class)
    return NukeListNodesResultSuccess(nodes=nodes, result_details=f"Listed {len(nodes)} nodes.")


def handle_get_node(request: NukeGetNodeRequest) -> NukeGetNodeResultSuccess | NukeGetNodeResultFailure:
    node = current_session().get_node(request.node_name)
    if node is None:
        return NukeGetNodeResultFailure(result_details=_no_such_node("read", request.node_name))
    return NukeGetNodeResultSuccess(node=node.describe(), result_details=f"Read node '{node.name}'.")


def handle_set_knob(request: NukeSetKnobRequest) -> NukeSetKnobResultSuccess | NukeSetKnobResultFailure:
    session = current_session()
    node = session.get_node(request.node_name)
    if node is None:
        return NukeSetKnobResultFailure(result_details=_no_such_node("set a knob on", request.node_name))
    previous = session.set_knob(node, request.knob, request.value)
    return NukeSetKnobResultSuccess(
        node_name=node.name,
        knob=request.knob,
        previous_value=previous,
        value=request.value,
        result_details=f"Set '{node.name}.{request.knob}' to {request.value!r}.",
    )


def handle_create_node(request: NukeCreateNodeRequest) -> NukeCreateNodeResultSuccess | NukeCreateNodeResultFailure:
    session = current_session()
    if request.node_name and session.get_node(request.node_name) is not None:
        return NukeCreateNodeResultFailure(
            result_details=f"Attempted to create node '{request.node_name}'. Failed because the script "
            "already has a node with that name."
        )
    if request.input_node and session.get_node(request.input_node) is None:
        return NukeCreateNodeResultFailure(result_details=_no_such_node("connect a node to", request.input_node))
    node = session.create_node(request.node_class, request.node_name, request.input_node, request.knobs)
    return NukeCreateNodeResultSuccess(node=node.describe(), result_details=f"Created {node.node_class} '{node.name}'.")


def handle_save_new_version(request: NukeSaveNewVersionRequest) -> NukeSaveNewVersionResultSuccess:  # noqa: ARG001
    session = current_session()
    path = session.save_new_version()
    return NukeSaveNewVersionResultSuccess(
        script_path=path,
        script_version=f"v{session.script_version:03d}",
        result_details=f"Saved {path}.",
    )


def handle_render(request: NukeRenderRequest) -> NukeRenderResultSuccess | NukeRenderResultFailure:
    session = current_session()
    node = session.get_node(request.write_node)
    if node is None:
        return NukeRenderResultFailure(result_details=_no_such_node("render", request.write_node))
    if node.node_class != "Write":
        return NukeRenderResultFailure(
            result_details=f"Attempted to render '{node.name}'. Failed because it is a {node.node_class} node, "
            "not a Write node."
        )
    if node.disabled:
        return NukeRenderResultFailure(
            result_details=f"Attempted to render '{node.name}'. Failed because the Write node is disabled."
        )
    first = request.first_frame or int(node.knobs.get("first", session.first_frame))
    last = request.last_frame or int(node.knobs.get("last", session.last_frame))
    if last < first:
        return NukeRenderResultFailure(
            result_details=f"Attempted to render '{node.name}' frames {first}-{last}. Failed because the last "
            "frame comes before the first."
        )
    render = session.render(node, first, last)
    return NukeRenderResultSuccess(
        render=render.describe(),
        result_details=f"Rendered '{node.name}' frames {first}-{last} to {render.output_path}.",
    )


def handle_list_renders(request: NukeListRendersRequest) -> NukeListRendersResultSuccess:  # noqa: ARG001
    renders = [render.describe() for render in current_session().renders]
    return NukeListRendersResultSuccess(renders=renders, result_details=f"Listed {len(renders)} renders.")


def _no_such_node(action: str, node_name: str) -> str:
    return (
        f"Attempted to {action} node '{node_name}'. Failed because the open script has no node with that "
        "name. Call NukeListNodesRequest to see the node names."
    )


ROUTES: tuple[tuple[type[RequestPayload], Callable[..., ResultPayload]], ...] = (
    (NukeGetScriptInfoRequest, handle_get_script_info),
    (NukeListNodesRequest, handle_list_nodes),
    (NukeGetNodeRequest, handle_get_node),
    (NukeSetKnobRequest, handle_set_knob),
    (NukeCreateNodeRequest, handle_create_node),
    (NukeSaveNewVersionRequest, handle_save_new_version),
    (NukeRenderRequest, handle_render),
    (NukeListRendersRequest, handle_list_renders),
)

MCP_TOOLS: tuple[MCPTool, ...] = (
    MCPTool(NukeGetScriptInfoRequest, read_only=True),
    MCPTool(NukeListNodesRequest, read_only=True),
    MCPTool(NukeGetNodeRequest, read_only=True),
    MCPTool(NukeListRendersRequest, read_only=True),
    MCPTool(NukeSetKnobRequest),
    MCPTool(NukeCreateNodeRequest),
    MCPTool(NukeSaveNewVersionRequest),
    MCPTool(NukeRenderRequest),
)
