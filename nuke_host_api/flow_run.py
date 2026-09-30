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
_CANCEL: asyncio.Task[engine.Attempt[CancelFlowResultSuccess]] | None = None


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


def start(flow_name: str) -> None:
    global _RUN, _CANCEL  # noqa: PLW0603
    run_outcome.begin_host_run()
    _CANCEL = None
    _RUN = asyncio.create_task(_run(flow_name))


async def cancel(flow_name: str) -> engine.Attempt[CancelFlowResultSuccess]:
    """The start answers mid-cancel, before the engine reports it, so the run awaits this too."""
    global _CANCEL  # noqa: PLW0603
    _CANCEL = asyncio.create_task(engine.request(CancelFlowRequest(flow_name=flow_name), CancelFlowResultSuccess))
    return await _CANCEL


def pending() -> bool:
    """True from reservation until the run's verdict is published."""
    return _RESERVED or (_RUN is not None and not _RUN.done())


async def busy() -> bool:
    return pending() or await engine.is_running()


async def _run(flow_name: str) -> None:
    """Every terminal engine event precedes the start's answer, so the verdict is complete here."""
    failure: str | None = f"the start request for flow '{flow_name}' ended without an answer."
    try:
        started = await engine.request(
            StartFlowRequest(flow_name=flow_name, wait_for_completion=True), StartFlowResultSuccess
        )
        failure = (
            None if started.value is not None else f"the engine reported flow '{flow_name}' failed. {started.details}"
        )
    finally:
        if _CANCEL is not None and not _CANCEL.done():
            await asyncio.wait({_CANCEL})
        # A run left open would hold every later editor run's verdict.
        if failure is not None:
            logger.error("Nuke host API: %s", failure)
        execution_bridge.publish(run_outcome.conclude(failure))
