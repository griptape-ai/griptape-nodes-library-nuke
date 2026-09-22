"""Tests for the detached flow start."""

from __future__ import annotations

from typing import Any

import pytest
from griptape_nodes.retained_mode.events.execution_events import (
    GetFlowStateRequest,
    StartFlowRequest,
    StartFlowResultFailure,
    StartFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.flow_events import (
    GetTopLevelFlowRequest,
    GetTopLevelFlowResultSuccess,
)

from nuke_host_api import execution_bridge, flow_run
from nuke_host_api.protocol import ExecutionState
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
    """The point of the module: a caller that awaited the start would wait out the whole run."""
    engine = use_engine(monkeypatch, STARTS)

    flow_run.start("main")

    assert engine.requests == []
    await flow_run.settled()
    assert [type(request) for request in engine.requests] == [StartFlowRequest]


async def test_a_started_flow_is_pending_until_the_start_settles(monkeypatch: pytest.MonkeyPatch) -> None:
    use_engine(monkeypatch, STARTS)

    flow_run.start("main")
    assert flow_run.pending() is True

    await flow_run.settled()
    assert flow_run.pending() is False


async def test_an_idle_engine_is_busy_while_a_start_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine reports a flow running only once it picks the start up, and a run is one run."""
    use_engine(monkeypatch, {**STARTS, **IDLE})

    flow_run.start("main")

    assert await flow_run.busy() is True
    await flow_run.settled()
    assert await flow_run.busy() is False


async def test_a_reservation_is_busy_until_released(monkeypatch: pytest.MonkeyPatch) -> None:
    """Execute's preflight writes inputs, so a load or a set landing inside it must be refused too."""
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
    """Otherwise one bad request leaves every later execute refused as already executing."""
    with pytest.raises(RuntimeError), flow_run.reserve():
        raise RuntimeError

    assert flow_run.pending() is False


class _Unfinished:
    def done(self) -> bool:
        return False


async def test_a_failed_run_reaches_the_host_as_a_failed_execution_state(
    monkeypatch: pytest.MonkeyPatch, _published: list[Any]
) -> None:
    """The reply said the run started, so the engine's verdict has nowhere else to go."""
    use_engine(
        monkeypatch,
        {StartFlowRequest: StartFlowResultFailure(result_details="validation failed", validation_exceptions=[])},
    )

    flow_run.start("main")
    await flow_run.settled()

    assert len(_published) == 1
    assert _published[0].state == ExecutionState.FAILED
    assert "validation failed" in _published[0].detail


async def test_an_engine_that_raises_reaches_the_host_the_same_way(
    monkeypatch: pytest.MonkeyPatch, _published: list[Any]
) -> None:
    """Nothing awaits this task, so an exception left to propagate is lost with it."""

    def explode(_request: Any) -> Any:
        msg = "engine went away"
        raise RuntimeError(msg)

    use_engine(monkeypatch, {StartFlowRequest: explode})

    flow_run.start("main")
    await flow_run.settled()

    assert len(_published) == 1
    assert _published[0].state == ExecutionState.FAILED
    assert "engine went away" in _published[0].detail


async def test_a_clean_start_publishes_nothing(monkeypatch: pytest.MonkeyPatch, _published: list[Any]) -> None:
    """Progress is the engine's own event feed, which the bridge already forwards."""
    use_engine(monkeypatch, STARTS)

    flow_run.start("main")
    await flow_run.settled()

    assert _published == []
