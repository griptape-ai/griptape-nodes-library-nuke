"""Translate engine execution events into host notifications."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from griptape_nodes.retained_mode.events.base_events import AppEvent
from griptape_nodes.retained_mode.events.execution_events import (
    ControlFlowCancelledEvent,
    ControlFlowResolvedEvent,
    CurrentControlNodeEvent,
    CurrentDataNodeEvent,
    InvolvedNodesEvent,
    NodeErrorEvent,
    NodeFinishProcessEvent,
    NodeResolvedEvent,
    NodeStartProcessEvent,
    NodeUnresolvedEvent,
    ParameterValueUpdateEvent,
)
from griptape_nodes.retained_mode.events.parameter_events import AlterElementEvent
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.events import (
    NukeExecutionNodesEvent,
    NukeExecutionStateEvent,
    NukeNodeProgressEvent,
    NukeNodeStateEvent,
    NukeParameterValueEvent,
)
from nuke_host_api.protocol import ExecutionState, NodeState
from nuke_host_api.value_types import CONTROL_PARAM_TYPE, UnrepresentableValueError, normalize_value

if TYPE_CHECKING:
    from collections.abc import Callable

    from griptape_nodes.retained_mode.events.base_events import AppPayload, ExecutionPayload

logger = logging.getLogger("griptape_nodes")

# Set by the engine's ProgressBarComponent on its 0.0-1.0 parameter.
PROGRESS_BAR_UI_OPTION = "progress_bar"
# Standard library GriptapeProxyNode's status string. The engine has no generic status convention.
STATUS_PARAMETER = "generation_status"


@dataclass
class _NodeProgress:
    progress: float | None = None
    message: str = ""


def publish(payload: AppPayload) -> None:
    """``broadcast_app_event`` reaches in-process listeners only, so IPC needs ``put_event``."""
    GriptapeNodes.EventManager().put_event(AppEvent(payload=payload))


class ExecutionBridge:
    def __init__(self) -> None:
        self._installed = False
        # Keyed by running node. Each notification is a full snapshot, so a status change keeps a known fraction.
        self._progress: dict[str, _NodeProgress] = {}

    @property
    def installed(self) -> bool:
        return self._installed

    def _subscriptions(self) -> tuple[tuple[type[ExecutionPayload], Callable[[Any], None]], ...]:
        """Use one subscription list for installation and teardown."""
        return (
            (NodeStartProcessEvent, self._on_node_start),
            (CurrentDataNodeEvent, self._on_node_start),
            (CurrentControlNodeEvent, self._on_node_start),
            (NodeFinishProcessEvent, self._on_node_finish),
            (NodeResolvedEvent, self._on_node_resolved),
            (NodeUnresolvedEvent, self._on_node_unresolved),
            (NodeErrorEvent, self._on_node_error),
            (ParameterValueUpdateEvent, self._on_parameter_value),
            (AlterElementEvent, self._on_element_altered),
            (InvolvedNodesEvent, self._on_involved_nodes),
            (ControlFlowResolvedEvent, self._on_flow_resolved),
            (ControlFlowCancelledEvent, self._on_flow_cancelled),
        )

    def install(self) -> None:
        """Callbacks run synchronously on the emitting thread."""
        if self._installed:
            return

        event_manager = GriptapeNodes.EventManager()
        subscriptions = self._subscriptions()
        for event_type, callback in subscriptions:
            event_manager.add_listener_to_execution_event(event_type, callback)

        self._installed = True
        logger.info("Nuke host API: subscribed to %d execution event types", len(subscriptions))

    def uninstall(self) -> None:
        """Listeners outlive libraries and must be removed explicitly on reload."""
        if not self._installed:
            return

        event_manager = GriptapeNodes.EventManager()
        for event_type, callback in self._subscriptions():
            event_manager.remove_listener_for_execution_event(event_type, callback)

        self._installed = False
        self._progress.clear()
        logger.info("Nuke host API: unsubscribed from the execution event feed")

    def _emit(
        self,
        payload: NukeNodeStateEvent
        | NukeNodeProgressEvent
        | NukeParameterValueEvent
        | NukeExecutionStateEvent
        | NukeExecutionNodesEvent,
    ) -> None:
        publish(payload)

    def _emit_node_state(self, node_name: str, state: str, detail: str = "") -> None:
        if state != NodeState.RUNNING:
            self._progress.pop(node_name, None)
        self._emit(NukeNodeStateEvent(node_name=node_name, state=state, detail=detail))

    def end_all_progress(self) -> None:
        """Cancel and failure emit no per-node events and loop start nodes never resolve, so the flow end clears what is left."""
        self._progress.clear()

    def _on_node_start(self, event: NodeStartProcessEvent | CurrentDataNodeEvent | CurrentControlNodeEvent) -> None:
        """The engine emits no NodeStartProcessEvent, so current-node events mark a start.

        A control node gets both current-node events back to back; a node already tracked as running is skipped.
        """
        if event.node_name in self._progress:
            return
        self._progress[event.node_name] = _NodeProgress()
        self._emit_node_state(event.node_name, NodeState.RUNNING)

    def _on_node_finish(self, event: NodeFinishProcessEvent) -> None:
        # Process completion precedes output publication; resolution is the host-visible state.
        self._emit_node_state(event.node_name, NodeState.RESOLVED)

    def _on_node_resolved(self, event: NodeResolvedEvent) -> None:
        self._emit_node_state(event.node_name, NodeState.RESOLVED)

    def _on_node_unresolved(self, event: NodeUnresolvedEvent) -> None:
        self._emit_node_state(event.node_name, NodeState.UNRESOLVED)

    def _on_node_error(self, event: NodeErrorEvent) -> None:
        self._emit_node_state(event.node_name, NodeState.FAILED, event.error_message)

    def _on_parameter_value(self, event: ParameterValueUpdateEvent) -> None:
        """Drop control wiring and values with no host form; a bulk read reports the latter as unavailable."""
        if event.data_type == CONTROL_PARAM_TYPE:
            return

        try:
            descriptor = normalize_value(event.value, event.data_type)
        except UnrepresentableValueError as e:
            logger.debug("Not notifying %s.%s: %s", event.node_name, event.parameter_name, e)
            return
        self._emit(
            NukeParameterValueEvent(
                node_name=event.node_name,
                parameter_name=event.parameter_name,
                value=descriptor,
            )
        )

    def _on_element_altered(self, event: AlterElementEvent) -> None:
        """Only running nodes report progress; values written while idle are not progress."""
        details = event.element_details
        if details.get("modification_type") != "set":
            return
        snapshot = self._progress.get(details.get("node_name") or "")
        if snapshot is None:
            return

        value = details.get("value")
        ui_options = details.get("ui_options") or {}
        if ui_options.get(PROGRESS_BAR_UI_OPTION):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return
            snapshot.progress = min(max(float(value), 0.0), 1.0)
        elif details.get("parameter_name") == STATUS_PARAMETER:
            snapshot.message = value if isinstance(value, str) else ""
        else:
            return

        self._emit(
            NukeNodeProgressEvent(
                node_name=details["node_name"],
                progress=snapshot.progress,
                message=snapshot.message,
            )
        )

    def _on_involved_nodes(self, event: InvolvedNodesEvent) -> None:
        self._emit(NukeExecutionNodesEvent(involved_nodes=list(event.involved_nodes)))

    def _on_flow_resolved(self, event: ControlFlowResolvedEvent) -> None:
        """Resolved events expose neither outcome nor declared outputs."""
        self.end_all_progress()
        self._emit(
            NukeExecutionStateEvent(
                state=ExecutionState.COMPLETED,
                terminal_node=event.end_node_name,
                detail="The engine reported the flow finished. It did not report an outcome.",
            )
        )

    def _on_flow_cancelled(self, event: ControlFlowCancelledEvent) -> None:
        self.end_all_progress()
        detail = str(event.result_details) if event.result_details else "Workflow cancelled."
        self._emit(NukeExecutionStateEvent(state=ExecutionState.CANCELLED, detail=detail))


# Process-wide so connect handlers can install it and library teardown can remove it.
_BRIDGE = ExecutionBridge()


def ensure_installed() -> None:
    """Install once because the engine exposes no disconnect signal for reference counting."""
    _BRIDGE.install()


def uninstall() -> None:
    """Remove the process-wide listener to prevent duplicate notifications after reload."""
    _BRIDGE.uninstall()


def end_all_progress() -> None:
    _BRIDGE.end_all_progress()


def is_installed() -> bool:
    return _BRIDGE.installed
