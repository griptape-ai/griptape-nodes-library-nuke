"""Bridge from engine execution events to host notifications.

Requests travel host -> engine and are handled by ``get_request_handlers()``. Events
travel the other way and need their own translation, or a host ends up subscribing to
raw engine execution events and binding to engine vocabulary after all.

So this module subscribes in-process to the engine's execution events, collapses them
into the small host set, and re-emits them as ``AppEvent``-wrapped host payloads.
``put_event`` is what reaches IPC; ``broadcast_app_event`` only notifies in-process
listeners and would never reach the host.

Eight engine event types collapse into four node states. That ratio is the point: the
engine is free to add a ninth without the host learning anything new.

Installed on the first ``NukeConnectRequest`` and torn down when the library unloads. The
subscription is engine-global, so an engine no host has spoken to should not pay for it;
see ``ensure_installed``.

Stateless by design. The bridge holds no execution state beyond its own subscription
flag. Values a host wants are read from the engine on demand via
NukeGetExecutionStateRequest, so there is no copy of engine state here to go stale.

One callback is not request-free. ``_on_parameter_value`` normalizes every streamed
value through the same ``normalize_value`` used everywhere else, and that normalizer
issues a synchronous ``GetPathForMacroRequest`` for any macro-bearing value. A
macro-templated Write path streams on every frame during a render, so this is a common
case, not an edge one, and it runs on the thread emitting the execution event. This is
accepted rather than avoided: skipping macro resolution on this path would hand a host a
MACRO source on the live update and a PATH source from NukeGetExecutionStateRequest for
the same value, breaking the single-value-format promise the normalizer exists to keep.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from griptape_nodes.retained_mode.events.base_events import AppEvent
from griptape_nodes.retained_mode.events.execution_events import (
    ControlFlowCancelledEvent,
    ControlFlowResolvedEvent,
    NodeErrorEvent,
    NodeFinishProcessEvent,
    NodeResolvedEvent,
    NodeStartProcessEvent,
    NodeUnresolvedEvent,
    ParameterValueUpdateEvent,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.events import (
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
    """Subscribes to engine execution events and emits host notifications."""

    def __init__(self) -> None:
        self._installed = False

    @property
    def installed(self) -> bool:
        return self._installed

    def _subscriptions(self) -> tuple[tuple[type[ExecutionPayload], Callable[[Any], None]], ...]:
        """Return the (engine event type, callback) pairs this bridge listens for.

        One list, used by both install and uninstall, so the two cannot drift.
        """
        return (
            (NodeStartProcessEvent, self._on_node_start),
            (NodeFinishProcessEvent, self._on_node_finish),
            (NodeResolvedEvent, self._on_node_resolved),
            (NodeUnresolvedEvent, self._on_node_unresolved),
            (NodeErrorEvent, self._on_node_error),
            (ParameterValueUpdateEvent, self._on_parameter_value),
            (ControlFlowResolvedEvent, self._on_flow_resolved),
            (ControlFlowCancelledEvent, self._on_flow_cancelled),
        )

    def install(self) -> None:
        """Subscribe to the engine's execution event feed.

        Only exact payload types match, so every event of interest is listed. Callbacks
        run synchronously on the emitting thread and must stay cheap.
        """
        if self._installed:
            return

        event_manager = GriptapeNodes.EventManager()
        subscriptions = self._subscriptions()
        for event_type, callback in subscriptions:
            event_manager.add_listener_to_execution_event(event_type, callback)

        self._installed = True
        logger.info("Nuke host API: subscribed to %d execution event types", len(subscriptions))

    def uninstall(self) -> None:
        """Unsubscribe from the event feed.

        Not optional. Listeners outlive the library that added them, so a reload without
        this leaves the previous bridge subscribed and a host receives every notification
        twice, then three times, and so on.

        The engine warns that a callback can still fire once more after removal if
        another thread already snapshotted the listener set, so callbacks stay tolerant
        of a late invocation.
        """
        if not self._installed:
            return

        event_manager = GriptapeNodes.EventManager()
        for event_type, callback in self._subscriptions():
            event_manager.remove_listener_for_execution_event(event_type, callback)

        self._installed = False
        logger.info("Nuke host API: unsubscribed from the execution event feed")

    def _emit(self, payload: NukeNodeStateEvent | NukeParameterValueEvent | NukeExecutionStateEvent) -> None:
        """Queue a host notification for broadcast over every IPC transport."""
        GriptapeNodes.EventManager().put_event(AppEvent(payload=payload))

    def _emit_node_state(self, node_name: str, state: str, detail: str = "") -> None:
        self._emit(NukeNodeStateEvent(node_name=node_name, state=state, detail=detail))

    def _on_node_start(self, event: NodeStartProcessEvent) -> None:
        self._emit_node_state(event.node_name, NodeState.RUNNING)

    def _on_node_finish(self, event: NodeFinishProcessEvent) -> None:
        # Finish means "process() returned", not "outputs are published". Resolution is
        # the state a host cares about, so this only moves a node out of running when
        # no resolution follows.
        self._emit_node_state(event.node_name, NodeState.RESOLVED)

    def _on_node_resolved(self, event: NodeResolvedEvent) -> None:
        self._emit_node_state(event.node_name, NodeState.RESOLVED)

    def _on_node_unresolved(self, event: NodeUnresolvedEvent) -> None:
        self._emit_node_state(event.node_name, NodeState.UNRESOLVED)

    def _on_node_error(self, event: NodeErrorEvent) -> None:
        self._emit_node_state(event.node_name, NodeState.FAILED, event.error_message)

    def _on_parameter_value(self, event: ParameterValueUpdateEvent) -> None:
        """Normalize the value before it leaves the process, and drop execution wiring.

        This is where the value contract earns its keep on the live path: the same
        normalizer that powers describe_workflow also shapes every streamed update, so
        a host has one value format rather than two.

        Control parameters are skipped. The engine streams a value update for ``exec_in``
        like any other parameter, and forwarding it would contradict describe_workflow,
        which never lists control parameters, and would type execution wiring as GTText because
        the normalizer has no case for a control type.
        """
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

    def _on_flow_resolved(self, event: ControlFlowResolvedEvent) -> None:
        """Report that the engine finished the flow, without reading any values or claiming an outcome.

        Values are deliberately not gathered here. The engine asks listeners to stay
        cheap and non-blocking, and issuing engine requests from inside an execution
        event callback would violate that. A host reads outputs with
        NukeGetExecutionStateRequest instead.

        ControlFlowResolvedEvent fires on both a clean run and an errored one, and carries
        no status field, so COMPLETED is all this layer actually knows. It must not infer
        success or failure from anything else observed here: NodeErrorEvent fires from
        several sites in the engine's resolution machine, and paths exist where it fires
        with no ControlFlowResolvedEvent following it (a cancel, a single-node-resolution
        exception), so latching on it would misreport the next run instead of this one.
        """
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


# One bridge per process. Owned here rather than by the advanced library module so that
# handle_connect can reach it without importing that module, which imports the handlers.
_BRIDGE = ExecutionBridge()


def ensure_installed() -> None:
    """Subscribe to the engine's execution feed, unless already subscribed.

    Called when a host connects, not when the library loads. The subscription is
    engine-global: the engine keys execution listeners by event type, not by library or
    node, so an installed bridge translates and re-emits for *every* workflow the engine
    runs, including ones with no Nuke nodes driven entirely from the editor. Installing at
    load time made anyone who merely has this library installed pay that, even with no
    transport enabled for a host to arrive on.

    Latching on rather than reference counting is deliberate. The transport gives Python no
    disconnect signal, so there is nothing to count down. An idle timeout would be the
    obvious substitute and is wrong: a host waiting on a twenty-minute render sends no
    requests, and that is the moment the stream must not stop.
    """
    _BRIDGE.install()


def uninstall() -> None:
    """Tear down the process-wide bridge.

    Not optional. Listeners outlive the library that added them, so a reload without this
    leaves the previous bridge subscribed and a host receives every notification twice.
    """
    _BRIDGE.uninstall()


def is_installed() -> bool:
    return _BRIDGE.installed
