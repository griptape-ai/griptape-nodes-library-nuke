"""No Nuke and no engine process: a real engine in-process, driven through the host handlers."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from griptape_nodes.exe_types.node_types import BaseNode
from griptape_nodes.retained_mode.events.connection_events import CreateConnectionRequest, DeleteConnectionRequest
from griptape_nodes.retained_mode.events.object_events import RenameObjectRequest
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api import execution_bridge, loaded_workflow, notify
from nuke_host_api.events import (
    NukeCancelExecutionRequest,
    NukeCancelExecutionResultSuccess,
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultSuccess,
    NukeExecutionStateEvent,
    NukeLoadWorkflowRequest,
    NukeLoadWorkflowResultSuccess,
)
from nuke_host_api.handlers import handle_cancel_execution, handle_execute_workflow, handle_load_workflow
from nuke_host_api.protocol import ExecutionState
from tests.detached_run import settled

from .fixtures.canary.canary_workflow_builder import build_start_canary_end_flow

if TYPE_CHECKING:
    from collections.abc import Iterator

DATA_NODE = "Canary"


def _data_node() -> BaseNode:
    with loaded_workflow.bound():
        node = GriptapeNodes.ObjectManager().attempt_get_object_by_name_as_type(DATA_NODE, BaseNode)
    assert node is not None
    return node


async def _load(workflow_id: str) -> None:
    """Load the workflow the builder saved, which the host's verbs then act on."""
    result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id=workflow_id))
    assert isinstance(result, NukeLoadWorkflowResultSuccess), result.result_details


def _rewire_control(source: str, target: str, *, via: str) -> None:
    deleted = GriptapeNodes.handle_request(
        DeleteConnectionRequest(
            source_node_name=source,
            source_parameter_name="exec_out",
            target_node_name=target,
            target_parameter_name="exec_in",
        )
    )
    assert deleted.succeeded(), deleted
    for hop_source, hop_target in ((source, via), (via, target)):
        created = GriptapeNodes.handle_request(
            CreateConnectionRequest(
                source_node_name=hop_source,
                source_parameter_name="exec_out",
                target_node_name=hop_target,
                target_parameter_name="exec_in",
            )
        )
        assert created.succeeded(), created


@pytest.fixture
def verdicts(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[NukeExecutionStateEvent]]:
    published: list[NukeExecutionStateEvent] = []

    def capture(payload: Any) -> None:
        if isinstance(payload, NukeExecutionStateEvent):
            published.append(payload)

    monkeypatch.setattr(notify, "publish", capture)
    execution_bridge.ensure_installed()
    yield published
    execution_bridge.uninstall()


async def test_a_clean_run_is_published_as_succeeded(
    tmp_path: Any, monkeypatch: Any, verdicts: list[NukeExecutionStateEvent]
) -> None:
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="outcome_clean", data_node_name=DATA_NODE)
    await _load("outcome_clean")

    result = await handle_execute_workflow(NukeExecuteWorkflowRequest())
    assert isinstance(result, NukeExecuteWorkflowResultSuccess), result

    await settled()
    assert [v.state for v in verdicts] == [ExecutionState.SUCCEEDED], verdicts


async def test_a_node_error_is_published_as_failed(
    tmp_path: Any, monkeypatch: Any, verdicts: list[NukeExecutionStateEvent]
) -> None:
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="outcome_error", data_node_name=DATA_NODE)
    await _load("outcome_error")
    node = _data_node()

    def raise_boom(*args: Any, **kwargs: Any) -> Any:
        msg = "boom from the outcome test"
        raise RuntimeError(msg)

    node.process = raise_boom

    result = await handle_execute_workflow(NukeExecuteWorkflowRequest())
    assert isinstance(result, NukeExecuteWorkflowResultSuccess), result

    await settled()
    assert [v.state for v in verdicts] == [ExecutionState.FAILED], verdicts
    assert "boom from the outcome test" in verdicts[0].detail


async def test_a_run_that_never_reaches_end_flow_is_published_as_failed(
    tmp_path: Any, monkeypatch: Any, verdicts: list[NukeExecutionStateEvent]
) -> None:
    """The engine reports success when a control chain stops short (griptape-nodes-engine#6210)."""
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="outcome_no_end", data_node_name=DATA_NODE)
    _rewire_control("Start", "End", via=DATA_NODE)
    await _load("outcome_no_end")
    # Stands in for any node the engine finishes without following, like a Subflow Node Group.
    monkeypatch.setattr(_data_node(), "get_next_control_output", lambda: None)

    result = await handle_execute_workflow(NukeExecuteWorkflowRequest())
    assert isinstance(result, NukeExecuteWorkflowResultSuccess), result

    await settled()
    assert [v.state for v in verdicts] == [ExecutionState.FAILED], verdicts
    assert "'End'" in verdicts[0].detail


async def test_an_end_flow_renamed_since_the_last_save_still_counts_as_reached(
    tmp_path: Any, monkeypatch: Any, verdicts: list[NukeExecutionStateEvent]
) -> None:
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="outcome_renamed_end", data_node_name=DATA_NODE)
    renamed = GriptapeNodes.handle_request(RenameObjectRequest(object_name="End", requested_name="Final"))
    assert renamed.succeeded(), renamed
    await _load("outcome_renamed_end")

    result = await handle_execute_workflow(NukeExecuteWorkflowRequest())
    assert isinstance(result, NukeExecuteWorkflowResultSuccess), result

    await settled()
    assert [v.state for v in verdicts] == [ExecutionState.SUCCEEDED], verdicts


async def test_a_mid_run_cancel_is_published_as_cancelled(
    tmp_path: Any, monkeypatch: Any, verdicts: list[NukeExecutionStateEvent]
) -> None:
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="outcome_cancel", data_node_name=DATA_NODE)
    await _load("outcome_cancel")
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

    for _ in range(500):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set(), "the node never started, so the cancel would not land mid-run"

    cancelled = await handle_cancel_execution(NukeCancelExecutionRequest())
    assert isinstance(cancelled, NukeCancelExecutionResultSuccess), cancelled
    assert node.is_cancellation_requested

    await settled()
    assert [v.state for v in verdicts] == [ExecutionState.CANCELLED], verdicts
