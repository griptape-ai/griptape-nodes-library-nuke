"""The workflow the host's last load named, the only one host verbs act on while the engine has others open."""

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
    # False for a workflow the host found open, such as an editor tab, which the host never closes.
    opened_by_host: bool


_LOADED: LoadedWorkflow | None = None


def record(open_id: str, name: str, *, opened_by_host: bool) -> None:
    global _LOADED  # noqa: PLW0603
    _LOADED = LoadedWorkflow(open_id=open_id, name=name, opened_by_host=opened_by_host)


def forget() -> None:
    global _LOADED  # noqa: PLW0603
    _LOADED = None


def current() -> LoadedWorkflow | None:
    """The host's workflow, or None when it loaded none or the workflow was closed elsewhere."""
    if _LOADED is None or engine.open_workflow(_LOADED.open_id) is None:
        return None
    return _LOADED


def workflow_id() -> str:
    """The host's workflow by registry name, else empty."""
    loaded = current()
    if loaded is None:
        return ""
    return loaded.name


@contextmanager
def bound() -> Iterator[None]:
    """Name the host's workflow on every request in the block. With none loaded, name none."""
    runtime = _runtime()
    if runtime is None:
        yield
        return
    with engine.bind_workflow(runtime):
        yield


async def flow_name() -> str | None:
    """The host's workflow's top-level flow, or None when the host loaded none."""
    if _runtime() is None:
        return None
    with bound():
        return await engine.top_level_flow_name()


async def declared_shape() -> dict:
    """Read from the graph, not the registry's last-saved shape, so unsaved edits count; empty with none loaded or no Start or End node."""
    loaded = current()
    if loaded is None:
        return {}
    with bound():
        attempt = await engine.workflow_shape(loaded.name)
    if attempt.value is None:
        return {}
    return attempt.value.workflow_shape.model_dump()


async def running() -> bool:
    """Whether the host's workflow is running. False when the host loaded none."""
    if _runtime() is None:
        return False
    with bound():
        return await engine.is_running()


def emitted_elsewhere() -> bool:
    """True when the emitting work is bound to an open workflow other than the host's."""
    emitter = getattr(bound_workflow.get(), "workflow_id", None)
    if emitter is None:
        return False
    loaded = current()
    return loaded is None or emitter != loaded.open_id


def _runtime() -> WorkflowRuntime | None:
    if _LOADED is None:
        return None
    return engine.open_workflow(_LOADED.open_id)
