"""A resolved data node reruns only when execute unresolves the flow first.

No Nuke and no engine process: a real engine in-process, driven through the host handler.
Reproduces griptape-ai/internal#261. Control nodes are unresolved as control re-enters them, so
only a data node shows the reuse the issue reports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from griptape_nodes.retained_mode.events.execution_events import NodeResolvedEvent
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.events import NukeExecuteWorkflowRequest, NukeExecuteWorkflowResultSuccess
from nuke_host_api.handlers import handle_execute_workflow
from tests.detached_run import settled

from .fixtures.canary.canary_workflow_builder import build_start_canary_end_flow

if TYPE_CHECKING:
    from pathlib import Path

DATA_NODE = "Canary"


async def _execute(**fields: Any) -> None:
    result = await handle_execute_workflow(NukeExecuteWorkflowRequest(**fields))
    assert isinstance(result, NukeExecuteWorkflowResultSuccess), result.result_details
    await settled()


@pytest.fixture
async def resolved_nodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Build Start -> End with a data node feeding End, run it once, and report what resolved.

    Async because the event queue the engine app installs at boot is bound to the running loop;
    created outside one, the engine dispatches nothing and a node resolving is unobservable.
    """
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="rerun_canary", data_node_name=DATA_NODE)

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
