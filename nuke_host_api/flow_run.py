from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING

from griptape_nodes.retained_mode.events.execution_events import StartFlowRequest, StartFlowResultSuccess

from nuke_host_api import engine, execution_bridge
from nuke_host_api.events import NukeExecutionStateEvent
from nuke_host_api.protocol import ExecutionState

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("griptape_nodes")

# Keep a strong reference to the detached task until the run ends.
_RUN: asyncio.Task[None] | None = None
_RESERVED = False


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
    global _RUN  # noqa: PLW0603
    _RUN = asyncio.create_task(_run(flow_name))


def pending() -> bool:
    """True from reservation until the engine answers the start, which it does when the flow ends."""
    return _RESERVED or (_RUN is not None and not _RUN.done())


async def busy() -> bool:
    return pending() or await engine.is_running()


async def settled() -> None:
    """Await the run without letting a cancelled waiter cancel it."""
    if _RUN is not None:
        await asyncio.shield(_RUN)


async def _run(flow_name: str) -> None:
    try:
        started = await engine.request(
            StartFlowRequest(flow_name=flow_name, wait_for_completion=True), StartFlowResultSuccess
        )
    except Exception as error:
        _report_failure(f"the engine raised while running flow '{flow_name}'. {error}")
        return
    if started.value is None:
        _report_failure(f"the engine reported flow '{flow_name}' failed. {started.details}")


def _report_failure(detail: str) -> None:
    """The reply already said the run started, so the engine's verdict has nowhere to go but the stream."""
    logger.error("Nuke host API: %s", detail)
    execution_bridge.publish(NukeExecutionStateEvent(state=ExecutionState.FAILED, detail=detail))
