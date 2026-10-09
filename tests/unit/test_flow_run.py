from __future__ import annotations

import asyncio
from typing import Any

import pytest
from griptape_nodes.retained_mode.events.execution_events import (
    CancelFlowRequest,
    CancelFlowResultSuccess,
    GetFlowStateRequest,
    StartFlowRequest,
    StartFlowResultFailure,
    StartFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.flow_events import (
    GetTopLevelFlowRequest,
    GetTopLevelFlowResultSuccess,
)

from nuke_host_api import engine, execution_bridge, flow_run, run_outcome
from nuke_host_api.protocol import ExecutionState
from tests.detached_run import settled
from tests.unit.host_api_fakes import IDLE_FLOW, use_engine

STARTS = {StartFlowRequest: StartFlowResultSuccess(result_details="started")}
IDLE = {
    GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
    GetFlowStateRequest: IDLE_FLOW,
}


@pytest.fixture
def _published(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    published: list[Any] = []
    monkeypatch.setattr(execution_bridge, "publish", published.append)
    return published


async def test_the_start_request_is_not_issued_before_the_caller_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = use_engine(monkeypatch, STARTS)

    flow_run.start("main", "wf1")

    assert engine.requests == []
    await settled()
    assert [type(request) for request in engine.requests] == [StartFlowRequest]


async def test_a_started_flow_is_pending_until_the_start_settles(monkeypatch: pytest.MonkeyPatch) -> None:
    use_engine(monkeypatch, STARTS)

    flow_run.start("main", "wf1")
    assert flow_run.pending() is True

    await settled()
    assert flow_run.pending() is False


async def test_an_idle_engine_is_busy_while_a_start_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    use_engine(monkeypatch, {**STARTS, **IDLE})

    flow_run.start("main", "wf1")

    assert await flow_run.busy() is True
    await settled()
    assert await flow_run.busy() is False


async def test_a_reservation_is_busy_until_released(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loads and writes must also refuse during execute preflight."""
    use_engine(monkeypatch, IDLE)

    with flow_run.reserve() as reserved:
        assert reserved is True
        assert await flow_run.busy() is True

    assert await flow_run.busy() is False


def test_the_slot_cannot_be_reserved_twice_or_while_a_start_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    with flow_run.reserve() as first, flow_run.reserve() as second:
        assert (first, second) == (True, False)

    monkeypatch.setattr(flow_run, "_RUN", _Unfinished())
    with flow_run.reserve() as reserved:
        assert reserved is False


def test_a_preflight_that_raises_releases_the_slot() -> None:
    with pytest.raises(RuntimeError), flow_run.reserve():
        raise RuntimeError

    assert flow_run.pending() is False


class _Unfinished:
    def done(self) -> bool:
        return False


async def test_a_failed_run_reaches_the_host_as_a_failed_execution_state(
    monkeypatch: pytest.MonkeyPatch, _published: list[Any]
) -> None:
    use_engine(
        monkeypatch,
        {StartFlowRequest: StartFlowResultFailure(result_details="validation failed", validation_exceptions=[])},
    )

    flow_run.start("main", "wf1")
    await settled()

    assert len(_published) == 1
    assert _published[0].state == ExecutionState.FAILED
    assert "validation failed" in _published[0].detail


async def test_a_clean_run_publishes_one_success(monkeypatch: pytest.MonkeyPatch, _published: list[Any]) -> None:
    use_engine(monkeypatch, STARTS)

    flow_run.start("main", "wf1")
    await settled()

    assert [payload.state for payload in _published] == [ExecutionState.SUCCEEDED]


async def test_a_cancel_seen_during_the_run_wins_over_the_starts_success(
    monkeypatch: pytest.MonkeyPatch, _published: list[Any]
) -> None:
    """The engine answers a cancelled start with success."""
    use_engine(monkeypatch, STARTS)

    flow_run.start("main", "wf1")
    run_outcome.on_cancelled("stopped", "wf1")
    await settled()

    assert [payload.state for payload in _published] == [ExecutionState.CANCELLED]


async def test_a_start_that_raises_still_ends_the_run(monkeypatch: pytest.MonkeyPatch, _published: list[Any]) -> None:
    async def boom(*args: Any, **kwargs: Any) -> Any:
        msg = "socket gone"
        raise RuntimeError(msg)

    monkeypatch.setattr(engine, "request", boom)

    flow_run.start("main", "wf1")
    await settled()

    assert [payload.state for payload in _published] == [ExecutionState.FAILED]
    assert "socket gone" in _published[0].detail
    assert run_outcome.host_run() is False


async def test_a_start_that_answers_mid_cancel_waits_for_the_cancel(
    monkeypatch: pytest.MonkeyPatch, _published: list[Any]
) -> None:
    """The engine answers the start once the flow completes, before its cancel reports."""
    cancel_entered = asyncio.Event()

    async def request(payload: Any, success: type) -> Any:
        if isinstance(payload, CancelFlowRequest):
            cancel_entered.set()
            await asyncio.sleep(0.01)
            run_outcome.on_cancelled("stopped", "wf1")
            return engine.Attempt(CancelFlowResultSuccess(result_details="ok"), "ok")
        await cancel_entered.wait()
        return engine.Attempt(StartFlowResultSuccess(result_details="ok"), "ok")

    monkeypatch.setattr(engine, "request", request)

    flow_run.start("main", "wf1")
    await flow_run.cancel("main")
    await settled()

    assert [payload.state for payload in _published] == [ExecutionState.CANCELLED]


async def test_a_run_waits_for_every_overlapping_cancel(monkeypatch: pytest.MonkeyPatch, _published: list[Any]) -> None:
    release_first = asyncio.Event()
    both_sent = asyncio.Event()
    cancels = 0

    async def request(payload: Any, success: type) -> Any:
        nonlocal cancels
        if isinstance(payload, CancelFlowRequest):
            cancels += 1
            if cancels == 1:
                await release_first.wait()
                run_outcome.on_cancelled("first", "wf1")
            else:
                both_sent.set()
            return engine.Attempt(CancelFlowResultSuccess(result_details="ok"), "ok")
        await both_sent.wait()
        return engine.Attempt(StartFlowResultSuccess(result_details="ok"), "ok")

    monkeypatch.setattr(engine, "request", request)

    flow_run.start("main", "wf1")
    first = asyncio.create_task(flow_run.cancel("main"))
    await asyncio.sleep(0)
    await flow_run.cancel("main")
    await asyncio.sleep(0.01)
    assert _published == [], "the verdict must wait for the first cancel"
    release_first.set()
    await first
    await settled()

    assert [payload.state for payload in _published] == [ExecutionState.CANCELLED]


async def test_a_cancel_sent_while_the_run_waits_on_another_is_awaited_too(
    monkeypatch: pytest.MonkeyPatch, _published: list[Any]
) -> None:
    release = [asyncio.Event(), asyncio.Event()]
    cancels = 0

    async def request(payload: Any, success: type) -> Any:
        nonlocal cancels
        if isinstance(payload, CancelFlowRequest):
            mine = cancels
            cancels += 1
            await release[mine].wait()
            run_outcome.on_cancelled(f"cancel {mine}", "wf1")
            return engine.Attempt(CancelFlowResultSuccess(result_details="ok"), "ok")
        return engine.Attempt(StartFlowResultSuccess(result_details="ok"), "ok")

    monkeypatch.setattr(engine, "request", request)

    first = asyncio.create_task(flow_run.cancel("main"))
    await asyncio.sleep(0)
    flow_run.start("main", "wf1")
    await asyncio.sleep(0.01)
    second = asyncio.create_task(flow_run.cancel("main"))
    await asyncio.sleep(0)
    release[0].set()
    await first
    await asyncio.sleep(0.01)
    assert _published == [], "the verdict must wait for the cancel sent during the wait"
    release[1].set()
    await second
    await settled()

    assert [payload.state for payload in _published] == [ExecutionState.CANCELLED]
