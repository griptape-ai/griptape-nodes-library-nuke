"""The workflow the host loaded, which host verbs act on while the engine has others open."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from griptape_nodes.retained_mode.runtime.binding import bound_workflow

from nuke_host_api import engine

if TYPE_CHECKING:
    from collections.abc import Iterator

    from griptape_nodes.retained_mode.runtime.workflow_runtime import WorkflowRuntime


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


def acted_on() -> WorkflowRuntime | None:
    """What host verbs act on: the host's workflow, else the engine's only open workflow, else none.

    The only open workflow is how a host drives a graph an editor user opened.
    """
    if _LOADED is not None:
        runtime = engine.open_workflow(_LOADED.open_id)
        if runtime is not None:
            return runtime
    return engine.only_open_workflow()


async def workflow_id() -> str:
    """The host's workflow by registry name, else the engine's only open workflow, else empty."""
    loaded = current()
    if loaded is not None:
        return loaded.name
    with bound():
        return await engine.current_workflow_id()


@contextmanager
def bound() -> Iterator[None]:
    """Name `acted_on()` on every request in the block. The engine doesn't pick one for a request that names none."""
    runtime = acted_on()
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
