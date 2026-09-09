"""Translate engine execution events into host notifications."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from griptape_nodes.retained_mode.events.base_events import AppEvent
from griptape_nodes.retained_mode.events.execution_events import (
    ControlFlowCancelledEvent,
    ControlFlowResolvedEvent,
    InvolvedNodesEvent,
    NodeErrorEvent,
    NodeFinishProcessEvent,
    NodeResolvedEvent,
    NodeStartProcessEvent,
    NodeUnresolvedEvent,
    ParameterValueUpdateEvent,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.events import (
    NukeExecutionNodesEvent,
    NukeExecutionStateEvent,
    NukeNodeStateEvent,
    NukeParameterValueEvent,
)
from nuke_host_api.protocol import ExecutionState, NodeState
from nuke_host_api.value_types import CONTROL_PARAM_TYPE, normalize_value

if TYPE_CHECKING:
    from collections.abc import Callable

    from griptape_nodes.retained_mode.events.base_events import ExecutionPayload

logger = logging.getLogger("griptape_nodes")


class ExecutionBridge:
    def __init__(self) -> None:
        self._installed = False

    @property
    def installed(self) -> bool:
        return self._installed

    def _subscriptions(self) -> tuple[tuple[type[ExecutionPayload], Callable[[Any], None]], ...]:
        """Use one subscription list for installation and teardown."""
        return (
            (NodeStartProcessEvent, self._on_node_start),
            (NodeFinishProcessEvent, self._on_node_finish),
            (NodeResolvedEvent, self._on_node_resolved),
            (NodeUnresolvedEvent, self._on_node_unresolved),
            (NodeErrorEvent, self._on_node_error),
            (ParameterValueUpdateEvent, self._on_parameter_value),
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
        logger.info("Nuke host API: unsubscribed from the execution event feed")

    def _emit(
        self,
        payload: NukeNodeStateEvent | NukeParameterValueEvent | NukeExecutionStateEvent | NukeExecutionNodesEvent,
    ) -> None:
        GriptapeNodes.EventManager().put_event(AppEvent(payload=payload))

    def _emit_node_state(self, node_name: str, state: str, detail: str = "") -> None:
        self._emit(NukeNodeStateEvent(node_name=node_name, state=state, detail=detail))

    def _on_node_start(self, event: NodeStartProcessEvent) -> None:
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
        """Drop control wiring and normalize data values before emission."""
        if event.data_type == CONTROL_PARAM_TYPE:
            return

        descriptor = normalize_value(event.value, event.data_type)
        self._emit(
            NukeParameterValueEvent(
                node_name=event.node_name,
                parameter_name=event.parameter_name,
                value=descriptor,
            )
        )

    def _on_involved_nodes(self, event: InvolvedNodesEvent) -> None:
        self._emit(NukeExecutionNodesEvent(involved_nodes=list(event.involved_nodes)))

    def _on_flow_resolved(self, event: ControlFlowResolvedEvent) -> None:
        """Resolved events expose neither outcome nor declared outputs."""
        self._emit(
            NukeExecutionStateEvent(
                state=ExecutionState.COMPLETED,
                terminal_node=event.end_node_name,
                detail="The engine reported the flow finished. It did not report an outcome.",
            )
        )

    def _on_flow_cancelled(self, event: ControlFlowCancelledEvent) -> None:
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


def is_installed() -> bool:
    return _BRIDGE.installed
