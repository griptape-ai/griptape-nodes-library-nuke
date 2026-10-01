from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING

from griptape_nodes.retained_mode.events.execution_events import (
    CancelFlowRequest,
    CancelFlowResultSuccess,
    StartFlowRequest,
    StartFlowResultSuccess,
)

from nuke_host_api import engine, execution_bridge, run_outcome

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("griptape_nodes")

# Keep a strong reference to the detached task until the run ends.
_RUN: asyncio.Task[None] | None = None
_RESERVED = False
_CANCELS: set[asyncio.Task[engine.Attempt[CancelFlowResultSuccess]]] = set()


@contextmanager
def reserve() -> Iterator[bool]:
    """Reserve before execute's first await so a racing execute is refused before writing inputs."""
    global _RESERVED  # noqa: PLW0603
    if pending():
        yield False
        return
    _RESERVED = True
    try:
        yield True
    finally:
        _RESERVED = False


def start(flow_name: str, workflow_id: str) -> None:
    global _RUN  # noqa: PLW0603
    run_outcome.begin_host_run()
    _RUN = asyncio.create_task(_run(flow_name, workflow_id))


async def cancel(flow_name: str) -> engine.Attempt[CancelFlowResultSuccess]:
    """Track every cancel because the start request can finish before cancellation is reported."""
    task = asyncio.create_task(engine.request(CancelFlowRequest(flow_name=flow_name), CancelFlowResultSuccess))
    _CANCELS.add(task)
    task.add_done_callback(_CANCELS.discard)
    return await task


def pending() -> bool:
    """True from reservation until the run's verdict is published."""
    return _RESERVED or (_RUN is not None and not _RUN.done())


async def busy() -> bool:
    return pending() or await engine.is_running()


async def _run(flow_name: str, workflow_id: str) -> None:
    """Wait for pending cancels because their terminal events may follow the start response."""
    failure: str | None = f"the start request for flow '{flow_name}' ended without an answer."
    raised = False
    try:
        started = await engine.request(StartFlowRequest(flow_name=flow_name), StartFlowResultSuccess)
        failure = (
            None if started.value is not None else f"the engine reported flow '{flow_name}' failed. {started.details}"
        )
    except Exception as e:
        # Detached, so nothing would retrieve a re-raise; the verdict is the report.
        failure = f"the start request for flow '{flow_name}' raised: {e}"
        logger.exception("Nuke host API: %s", failure)
        raised = True
    finally:
        while _CANCELS:
            await asyncio.wait(set(_CANCELS))
        # A run left open would hold every later editor run's verdict.
        if failure is not None and not raised:
            logger.error("Nuke host API: %s", failure)
        execution_bridge.publish(run_outcome.conclude(failure, workflow_id))
