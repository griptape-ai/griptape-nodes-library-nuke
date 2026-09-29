"""A running node's progress bar and status string reach the host as progress snapshots.

No Nuke and no engine process: a real engine in-process, driven through the host handlers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import BaseNode
from griptape_nodes.exe_types.param_components.progress_bar_component import ProgressBarComponent
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api import execution_bridge
from nuke_host_api.events import (
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultSuccess,
    NukeNodeProgressEvent,
    NukeNodeStateEvent,
)
from nuke_host_api.execution_bridge import STATUS_PARAMETER
from nuke_host_api.handlers import handle_execute_workflow
from nuke_host_api.protocol import NodeState
from tests.detached_run import settled

from .fixtures.canary.canary_workflow_builder import build_start_canary_end_flow

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

DATA_NODE = "Canary"


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    payloads: list[Any] = []
    monkeypatch.setattr(execution_bridge, "publish", payloads.append)
    execution_bridge.ensure_installed()
    try:
        yield payloads
    finally:
        execution_bridge.uninstall()


def _progress_node() -> tuple[BaseNode, ProgressBarComponent]:
    node = GriptapeNodes.ObjectManager().attempt_get_object_by_name_as_type(DATA_NODE, BaseNode)
    assert node is not None
    progress_bar = ProgressBarComponent(node)
    progress_bar.add_property_parameters()
    node.add_parameter(Parameter(name=STATUS_PARAMETER, output_type="str", allowed_modes={ParameterMode.OUTPUT}))
    return node, progress_bar


async def test_a_running_node_streams_progress_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, published: list[Any]
) -> None:
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="node_progress", data_node_name=DATA_NODE)
    node, progress_bar = _progress_node()
    original_process = node.process

    def process(*args: Any, **kwargs: Any) -> Any:
        node.parameter_output_values[STATUS_PARAMETER] = "QUEUED"
        progress_bar.initialize(4)
        progress_bar.increment(2)
        node.parameter_output_values[STATUS_PARAMETER] = "RUNNING"
        progress_bar.increment(2)
        return original_process(*args, **kwargs)

    node.process = process

    result = await handle_execute_workflow(NukeExecuteWorkflowRequest())
    assert isinstance(result, NukeExecuteWorkflowResultSuccess), result
    await settled()

    node_events = [
        payload
        for payload in published
        if isinstance(payload, (NukeNodeStateEvent, NukeNodeProgressEvent)) and payload.node_name == DATA_NODE
    ]
    progress = [(event.progress, event.message) for event in node_events if isinstance(event, NukeNodeProgressEvent)]
    assert progress == [
        (None, "QUEUED"),
        (0.0, "QUEUED"),
        (0.5, "QUEUED"),
        (0.5, "RUNNING"),
        (1.0, "RUNNING"),
    ]

    states = [event.state if isinstance(event, NukeNodeStateEvent) else "progress" for event in node_events]
    first_progress = states.index("progress")
    assert NodeState.RUNNING in states[:first_progress]
    assert NodeState.RESOLVED in states[first_progress:]
