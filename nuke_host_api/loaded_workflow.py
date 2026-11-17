"""The workflow the host loaded, which host verbs act on while the engine has others open."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from griptape_nodes.retained_mode.runtime.binding import bound_workflow

from nuke_host_api import engine

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(frozen=True)
class LoadedWorkflow:
    """Opening a template makes a copy with its own id, so the open id and registry name can differ."""

    open_id: str
    name: str


_LOADED: LoadedWorkflow | None = None


def record(open_id: str, name: str) -> None:
    global _LOADED  # noqa: PLW0603
    _LOADED = LoadedWorkflow(open_id=open_id, name=name)


def forget() -> None:
    global _LOADED  # noqa: PLW0603
    _LOADED = None


def current() -> LoadedWorkflow | None:
    """The host's workflow, or None when it loaded none or the workflow was closed elsewhere."""
    if _LOADED is None or engine.open_workflow(_LOADED.open_id) is None:
        return None
    return _LOADED


async def workflow_id() -> str:
    """The host's workflow by registry name, else the engine's only open workflow, else empty."""
    loaded = current()
    if loaded is not None:
        return loaded.name
    return await engine.current_workflow_id()


@contextmanager
def bound() -> Iterator[None]:
    """Act on the host's workflow; with none, the engine falls back to its only open workflow."""
    runtime = engine.open_workflow(_LOADED.open_id) if _LOADED is not None else None
    if runtime is None:
        yield
        return
    with engine.bind_workflow(runtime):
        yield


def emitted_elsewhere() -> bool:
    """True when the emitting work is bound to an open workflow other than the host's."""
    loaded = current()
    if loaded is None:
        return False
    emitter = getattr(bound_workflow.get(), "workflow_id", None)
    return emitter is not None and emitter != loaded.open_id
