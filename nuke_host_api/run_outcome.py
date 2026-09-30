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
_last: NukeExecutionStateEvent | None = None


def begin_host_run() -> None:
    """Hold the verdict until the start request answers, which follows every terminal event."""
    global _host_run  # noqa: PLW0603
    with _LOCK:
        _reset()
        _host_run = True


def host_run() -> bool:
    with _LOCK:
        return _host_run


def note_node_error(message: str) -> None:
    global _node_error  # noqa: PLW0603
    with _LOCK:
        if not _node_error:
            _node_error = message or "A node failed."


def note_resolved(terminal_node: str) -> None:
    global _terminal_node  # noqa: PLW0603
    with _LOCK:
        _terminal_node = terminal_node


def note_cancelled(detail: str) -> None:
    global _cancel_detail  # noqa: PLW0603
    with _LOCK:
        _cancel_detail = detail


def conclude(start_failure: str | None = None) -> NukeExecutionStateEvent:
    global _last  # noqa: PLW0603
    with _LOCK:
        if start_failure is not None:
            state, detail = ExecutionState.FAILED, start_failure
        elif _cancel_detail is not None:
            state, detail = ExecutionState.CANCELLED, _cancel_detail
        elif _node_error:
            state, detail = ExecutionState.FAILED, _node_error
        else:
            state, detail = ExecutionState.SUCCEEDED, "Workflow finished."
        _last = NukeExecutionStateEvent(state=state, terminal_node=_terminal_node, detail=detail)
        _reset()
        return _last


def last() -> NukeExecutionStateEvent | None:
    with _LOCK:
        return _last


def clear() -> None:
    global _last  # noqa: PLW0603
    with _LOCK:
        _reset()
        _last = None


def _reset() -> None:
    global _host_run, _node_error, _cancel_detail, _terminal_node  # noqa: PLW0603
    _host_run = False
    _node_error = ""
    _cancel_detail = None
    _terminal_node = ""
