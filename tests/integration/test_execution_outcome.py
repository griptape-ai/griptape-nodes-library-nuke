"""A node error fails the execute reply; a mid-run cancel still replies success.

No Nuke and no engine process: a real engine in-process, driven through the host handlers.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from griptape_nodes.exe_types.node_types import BaseNode
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.events import (
    NukeCancelExecutionRequest,
    NukeCancelExecutionResultSuccess,
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultFailure,
    NukeExecuteWorkflowResultSuccess,
)
from nuke_host_api.handlers import handle_cancel_execution, handle_execute_workflow
from nuke_host_api.protocol import ExecutionState

from .fixtures.canary.canary_workflow_builder import build_start_canary_end_flow

DATA_NODE = "Canary"


def _data_node() -> BaseNode:
    node = GriptapeNodes.ObjectManager().attempt_get_object_by_name_as_type(DATA_NODE, BaseNode)
    assert node is not None
    return node


async def test_a_node_error_fails_the_execute_reply(tmp_path: Any, monkeypatch: Any) -> None:
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="outcome_error", data_node_name=DATA_NODE)
    node = _data_node()

    def raise_boom(*args: Any, **kwargs: Any) -> Any:
        msg = "boom from the outcome test"
        raise RuntimeError(msg)

    node.process = raise_boom

    result = await handle_execute_workflow(NukeExecuteWorkflowRequest())

    assert isinstance(result, NukeExecuteWorkflowResultFailure), result
    assert "boom from the outcome test" in str(result.result_details)
    assert result.applied_inputs == []
    assert result.rejected_inputs == []


async def test_a_mid_run_cancel_still_replies_success(tmp_path: Any, monkeypatch: Any) -> None:
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

    execute_task = asyncio.ensure_future(handle_execute_workflow(NukeExecuteWorkflowRequest()))
    for _ in range(500):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set(), "the node never started, so the cancel would not land mid-run"

    cancelled = await handle_cancel_execution(NukeCancelExecutionRequest())
    assert isinstance(cancelled, NukeCancelExecutionResultSuccess), cancelled
    assert node.is_cancellation_requested

    result = await execute_task
    assert isinstance(result, NukeExecuteWorkflowResultSuccess), result
    assert result.state == ExecutionState.COMPLETED
