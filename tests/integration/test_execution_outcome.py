"""A node error reaches the host as a failed event after the kickoff reply; a mid-run cancel does not.

No Nuke and no engine process: a real engine in-process, driven through the host handlers.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest
from griptape_nodes.exe_types.node_types import BaseNode
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api import execution_bridge, flow_run
from nuke_host_api.events import (
    NukeCancelExecutionRequest,
    NukeCancelExecutionResultSuccess,
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultSuccess,
    NukeExecutionStateEvent,
)
from nuke_host_api.handlers import handle_cancel_execution, handle_execute_workflow
from nuke_host_api.protocol import ExecutionState

from .fixtures.canary.canary_workflow_builder import build_start_canary_end_flow

DATA_NODE = "Canary"


def _data_node() -> BaseNode:
    node = GriptapeNodes.ObjectManager().attempt_get_object_by_name_as_type(DATA_NODE, BaseNode)
    assert node is not None
    return node


@pytest.fixture
def failures(monkeypatch: pytest.MonkeyPatch) -> list[NukeExecutionStateEvent]:
    published: list[NukeExecutionStateEvent] = []

    def capture(payload: Any) -> None:
        if isinstance(payload, NukeExecutionStateEvent) and payload.state == ExecutionState.FAILED:
            published.append(payload)

    monkeypatch.setattr(execution_bridge, "publish", capture)
    return published


async def test_a_node_error_is_published_as_failed(
    tmp_path: Any, monkeypatch: Any, failures: list[NukeExecutionStateEvent]
) -> None:
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="outcome_error", data_node_name=DATA_NODE)
    node = _data_node()

    def raise_boom(*args: Any, **kwargs: Any) -> Any:
        msg = "boom from the outcome test"
        raise RuntimeError(msg)

    node.process = raise_boom

    result = await handle_execute_workflow(NukeExecuteWorkflowRequest())
    assert isinstance(result, NukeExecuteWorkflowResultSuccess), result
    assert result.state == ExecutionState.RUNNING

    await flow_run.settled()
    assert len(failures) == 1, failures
    assert "boom from the outcome test" in failures[0].detail


async def test_a_mid_run_cancel_publishes_no_failure(
    tmp_path: Any, monkeypatch: Any, failures: list[NukeExecutionStateEvent]
) -> None:
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="outcome_cancel", data_node_name=DATA_NODE)
    node = _data_node()

    started = threading.Event()

    def slow_process(*args: Any, **kwargs: Any) -> Any:
        # A yielded step runs on a worker thread, leaving the loop free for the cancel request.
        def wait_for_cancel() -> None:
            started.set()
            deadline = time.monotonic() + 10
            while not node.is_cancellation_requested and time.monotonic() < deadline:
                time.sleep(0.01)

        yield wait_for_cancel

    node.process = slow_process

    result = await handle_execute_workflow(NukeExecuteWorkflowRequest())
    assert isinstance(result, NukeExecuteWorkflowResultSuccess), result
    assert result.state == ExecutionState.RUNNING

    for _ in range(500):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set(), "the node never started, so the cancel would not land mid-run"

    cancelled = await handle_cancel_execution(NukeCancelExecutionRequest())
    assert isinstance(cancelled, NukeCancelExecutionResultSuccess), cancelled
    assert node.is_cancellation_requested

    await flow_run.settled()
    assert failures == []
