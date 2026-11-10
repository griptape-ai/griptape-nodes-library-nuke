"""Derive run verdicts from engine terminal events."""

from __future__ import annotations

import threading

from nuke_host_api.events import NukeExecutionStateEvent
from nuke_host_api.protocol import ExecutionState

# Bridge callbacks run on engine worker threads; the host run concludes on the loop.
_LOCK = threading.Lock()
_host_run = False
_node_error = ""
_cancel_detail: str | None = None
_terminal_node = ""
# Reaching End Flow is what a host run promises; the engine reports success for a run whose control
# chain just stops (griptape-nodes-engine#6210).
_end_nodes: frozenset[str] = frozenset()
_reached_end = False
_last: NukeExecutionStateEvent | None = None
_last_workflow_id = ""


def begin_host_run(end_nodes: frozenset[str]) -> None:
    """Hold the verdict until the start request answers, and fail it unless one of ``end_nodes`` resolves."""
    global _host_run, _end_nodes  # noqa: PLW0603
    with _LOCK:
        _reset()
        _host_run = True
        _end_nodes = end_nodes


def host_run() -> bool:
    with _LOCK:
        return _host_run


def note_node_error(message: str) -> None:
    global _node_error  # noqa: PLW0603
    with _LOCK:
        if not _node_error:
            _node_error = message or "A node failed."


def note_node_resolved(node_name: str) -> None:
    global _reached_end  # noqa: PLW0603
    with _LOCK:
        if node_name in _end_nodes:
            _reached_end = True


def on_resolved(terminal_node: str, workflow_id: str) -> NukeExecutionStateEvent | None:
    global _terminal_node  # noqa: PLW0603
    with _LOCK:
        _terminal_node = terminal_node
        return None if _host_run else _conclude(None, workflow_id)


def on_cancelled(detail: str, workflow_id: str) -> NukeExecutionStateEvent | None:
    global _cancel_detail  # noqa: PLW0603
    with _LOCK:
        _cancel_detail = detail
        return None if _host_run else _conclude(None, workflow_id)


def conclude(start_failure: str | None, workflow_id: str) -> NukeExecutionStateEvent:
    with _LOCK:
        return _conclude(start_failure, workflow_id)


def last(workflow_id: str) -> NukeExecutionStateEvent | None:
    with _LOCK:
        return _last if _last is not None and _last_workflow_id == workflow_id else None


def clear() -> None:
    global _last, _last_workflow_id  # noqa: PLW0603
    with _LOCK:
        _reset()
        _last = None
        _last_workflow_id = ""


def _conclude(start_failure: str | None, workflow_id: str) -> NukeExecutionStateEvent:
    global _last, _last_workflow_id  # noqa: PLW0603
    if start_failure is not None:
        state, detail = ExecutionState.FAILED, start_failure
    elif _cancel_detail is not None:
        state, detail = ExecutionState.CANCELLED, _cancel_detail
    elif _node_error:
        state, detail = ExecutionState.FAILED, _node_error
    elif _end_nodes and not _reached_end:
        state, detail = ExecutionState.FAILED, _end_not_reached_detail()
    else:
        state, detail = ExecutionState.SUCCEEDED, "Workflow finished."
    _last = NukeExecutionStateEvent(state=state, terminal_node=_terminal_node, detail=detail)
    _last_workflow_id = workflow_id
    _reset()
    return _last


def _end_not_reached_detail() -> str:
    end_nodes = " or ".join(f"'{name}'" for name in sorted(_end_nodes))
    if _terminal_node:
        stopped = f"The run stopped at '{_terminal_node}'"
    else:
        stopped = "The run stopped"
    return f"{stopped} before {end_nodes} ran, so the workflow produced no outputs."


def _reset() -> None:
    global _host_run, _node_error, _cancel_detail, _terminal_node, _end_nodes, _reached_end  # noqa: PLW0603
    _host_run = False
    _node_error = ""
    _cancel_detail = None
    _terminal_node = ""
    _end_nodes = frozenset()
    _reached_end = False
