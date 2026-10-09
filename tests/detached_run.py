from __future__ import annotations

from nuke_host_api import flow_run


async def settled() -> None:
    """Await the run execute detached, so assertions see its outcome."""
    if flow_run._RUN is not None:
        await flow_run._RUN
