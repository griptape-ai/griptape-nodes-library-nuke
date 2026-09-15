"""A resolved data node reruns only when execute unresolves the flow first.

No Nuke and no engine process: a real engine in-process, driven through the host handler.
Reproduces griptape-ai/internal#261. Control nodes are unresolved as control re-enters them, so
only a data node shows the reuse the issue reports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from griptape_nodes.retained_mode.events.context_events import SetWorkflowContextRequest
from griptape_nodes.retained_mode.events.execution_events import NodeResolvedEvent
from griptape_nodes.retained_mode.events.flow_events import CreateFlowRequest, CreateFlowResultSuccess
from griptape_nodes.retained_mode.events.library_events import RegisterLibraryFromFileRequest
from griptape_nodes.retained_mode.events.parameter_events import AddParameterToNodeRequest
from griptape_nodes.retained_mode.events.workflow_events import SaveWorkflowRequest
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.events import NukeExecuteWorkflowRequest, NukeExecuteWorkflowResultSuccess
from nuke_host_api.handlers import handle_execute_workflow

from .fixtures.canary.canary_workflow_builder import (
    NUKE_LIBRARY_DIR,
    connect,
    create_node,
    materialize_canary_library,
)

if TYPE_CHECKING:
    from pathlib import Path

DATA_NODE = "Canary"


def _ok(result: Any) -> Any:
    assert result.succeeded(), result
    return result


async def _execute(**fields: Any) -> None:
    result = await handle_execute_workflow(NukeExecuteWorkflowRequest(**fields))
    assert isinstance(result, NukeExecuteWorkflowResultSuccess), result.result_details


@pytest.fixture
async def resolved_nodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Build Start -> End with a data node feeding End, run it once, and report what resolved.

    Async because the event queue the engine app installs at boot is bound to the running loop;
    created outside one, the engine dispatches nothing and a node resolving is unobservable.
    """
    workspace = tmp_path / "workspace"
    (workspace / "assets").mkdir(parents=True)
    (workspace / "assets" / "canary_asset.txt").write_text("canary asset\n")
    (workspace / "inputs").mkdir()
    (workspace / "inputs" / "canary_macro_asset.txt").write_text("canary input\n")
    monkeypatch.setenv("GTN_CONFIG_WORKSPACE_DIRECTORY", str(workspace))
    monkeypatch.setenv("GTN_CONFIG_ENABLE_WORKSPACE_FILE_WATCHING", "false")

    GriptapeNodes.EventManager().initialize_queue()

    nuke_library = NUKE_LIBRARY_DIR / "griptape-nodes-library.json"
    _ok(GriptapeNodes.handle_request(RegisterLibraryFromFileRequest(file_path=str(nuke_library))))
    canary_library = materialize_canary_library(tmp_path / "canary_library")
    _ok(GriptapeNodes.handle_request(RegisterLibraryFromFileRequest(file_path=str(canary_library))))

    _ok(GriptapeNodes.handle_request(SetWorkflowContextRequest()))
    flow = GriptapeNodes.handle_request(CreateFlowRequest(parent_flow_name=None, flow_name="ControlFlow_1"))
    assert isinstance(flow, CreateFlowResultSuccess), flow
    create_node("NukeStartFlow", "Start", flow.flow_name)
    create_node("CanaryNode", DATA_NODE, flow.flow_name)
    create_node("NukeEndFlow", "End", flow.flow_name)
    _ok(
        GriptapeNodes.handle_request(
            AddParameterToNodeRequest(
                node_name="End",
                parameter_name="output_path",
                default_value="",
                tooltip="",
                type="str",
                input_types=["str"],
                mode_allowed_output=False,
            )
        )
    )
    connect("Start", "exec_out", "End", "exec_in")
    # A data dependency rather than a link in the control chain: that is the shape the issue
    # reports, a generative node upstream of the graph that runs.
    connect(DATA_NODE, "output_path", "End", "output_path")
    _ok(GriptapeNodes.handle_request(SaveWorkflowRequest(file_name="rerun_canary")))

    resolved: list[str] = []
    GriptapeNodes.EventManager().add_listener_to_execution_event(
        NodeResolvedEvent, lambda event: resolved.append(event.node_name)
    )

    await _execute()
    assert DATA_NODE in resolved, "the first run must resolve the data node, or nothing below tests reuse"
    return resolved


async def test_an_unchanged_rerun_reuses_a_resolved_data_node(resolved_nodes: list[str]) -> None:
    """The engine behaviour the field exists for. A change here changes the premise."""
    resolved_nodes.clear()

    await _execute()

    assert DATA_NODE not in resolved_nodes, "a resolved data node is reused, which is why unresolve_first exists"


async def test_unresolve_first_reruns_a_resolved_data_node(resolved_nodes: list[str]) -> None:
    first = list(resolved_nodes)
    resolved_nodes.clear()

    await _execute(unresolve_first=True)

    assert sorted(resolved_nodes) == sorted(first), "an unresolved flow must rerun every node the first run ran"
