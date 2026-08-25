"""Tests for the outbound event bridge.

Two properties matter. Subscriptions must be symmetric, because a bridge that installs
more listeners than it removes duplicates every notification a host receives. And values
must be normalized before they leave, because the live path is where a host would
otherwise meet raw engine artifacts.
"""

from __future__ import annotations

from typing import Any

import pytest
from griptape.artifacts import ImageUrlArtifact
from griptape_nodes.retained_mode.events.base_events import AppEvent
from griptape_nodes.retained_mode.events.execution_events import (
    ControlFlowCancelledEvent,
    ControlFlowResolvedEvent,
    NodeErrorEvent,
    NodeStartProcessEvent,
    ParameterValueUpdateEvent,
)

from nuke_host_api import execution_bridge
from nuke_host_api.events import (
    NukeExecutionStateEvent,
    NukeNodeStateEvent,
    NukeParameterValueEvent,
)
from nuke_host_api.execution_bridge import ExecutionBridge
from nuke_host_api.protocol import ExecutionState, NodeState, ValueType
from nuke_host_api.value_types import CONTROL_PARAM_TYPE


class FakeEventManager:
    """Records subscriptions and emitted events."""

    def __init__(self) -> None:
        self.listeners: dict[type, set] = {}
        self.emitted: list[Any] = []

    def add_listener_to_execution_event(self, event_type: type, callback: Any) -> None:
        self.listeners.setdefault(event_type, set()).add(callback)

    def remove_listener_for_execution_event(self, event_type: type, callback: Any) -> None:
        self.listeners.get(event_type, set()).discard(callback)

    def put_event(self, event: Any) -> None:
        self.emitted.append(event)

    @property
    def listener_count(self) -> int:
        return sum(len(callbacks) for callbacks in self.listeners.values())

    def payloads(self) -> list[Any]:
        return [event.payload for event in self.emitted if isinstance(event, AppEvent)]


class FakeEngine:
    def __init__(self, event_manager: FakeEventManager) -> None:
        self._event_manager = event_manager

    def EventManager(self) -> FakeEventManager:  # noqa: N802
        return self._event_manager


@pytest.fixture
def event_manager(monkeypatch: pytest.MonkeyPatch) -> FakeEventManager:
    manager = FakeEventManager()
    monkeypatch.setattr(execution_bridge, "GriptapeNodes", FakeEngine(manager))
    return manager


class TestSubscriptionLifecycle:
    def test_install_subscribes_every_declared_event(self, event_manager: FakeEventManager) -> None:
        bridge = ExecutionBridge()
        bridge.install()
        assert event_manager.listener_count == len(bridge._subscriptions())

    def test_uninstall_removes_everything_install_added(self, event_manager: FakeEventManager) -> None:
        """The asymmetry that made a host receive every notification twice, then thrice.

        The engine deregisters request handlers on unload but not execution event
        listeners, so a reload without this leaves the previous bridge subscribed.
        """
        bridge = ExecutionBridge()
        bridge.install()
        bridge.uninstall()
        assert event_manager.listener_count == 0

    def test_install_is_idempotent(self, event_manager: FakeEventManager) -> None:
        bridge = ExecutionBridge()
        bridge.install()
        bridge.install()
        assert event_manager.listener_count == len(bridge._subscriptions())

    def test_uninstall_before_install_is_harmless(self, event_manager: FakeEventManager) -> None:
        ExecutionBridge().uninstall()
        assert event_manager.listener_count == 0

    def test_reinstall_after_uninstall_works(self, event_manager: FakeEventManager) -> None:
        bridge = ExecutionBridge()
        bridge.install()
        bridge.uninstall()
        bridge.install()
        assert event_manager.listener_count == len(bridge._subscriptions())

    def test_two_bridges_do_not_share_subscriptions(self, event_manager: FakeEventManager) -> None:
        """Two loaded copies double the stream, which is why unload must tear down."""
        first, second = ExecutionBridge(), ExecutionBridge()
        first.install()
        second.install()
        assert event_manager.listener_count == 2 * len(first._subscriptions())
        first.uninstall()
        assert event_manager.listener_count == len(second._subscriptions())


class TestTranslation:
    def test_node_start_becomes_running(self, event_manager: FakeEventManager) -> None:
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_node_start(NodeStartProcessEvent(node_name="Blur"))
        payload = event_manager.payloads()[-1]
        assert isinstance(payload, NukeNodeStateEvent)
        assert payload.node_name == "Blur"
        assert payload.state == NodeState.RUNNING

    def test_node_error_carries_the_message(self, event_manager: FakeEventManager) -> None:
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_node_error(NodeErrorEvent(node_name="Blur", error_message="kaboom"))
        payload = event_manager.payloads()[-1]
        assert payload.state == NodeState.FAILED
        assert payload.detail == "kaboom"

    def test_parameter_values_are_normalized_before_they_leave(self, event_manager: FakeEventManager) -> None:
        """The live path must not hand a host a raw artifact."""
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_parameter_value(
            ParameterValueUpdateEvent(
                node_name="Read",
                parameter_name="image",
                data_type="ImageUrlArtifact",
                value=ImageUrlArtifact("http://localhost:8124/workspace/static_files/a.png"),
            )
        )
        payload = event_manager.payloads()[-1]
        assert isinstance(payload, NukeParameterValueEvent)
        assert payload.value["value_type"] == ValueType.IMAGE
        assert payload.value["sources"][0]["format"] == "png"

    def test_a_control_flow_parameter_update_is_not_forwarded(self, event_manager: FakeEventManager) -> None:
        """The engine streams a value update for exec_in like any other parameter.

        Forwarding it would contradict describe_workflow, which never lists control ports,
        and would type execution wiring as GTText, since the normalizer has no case for a
        control type. Observed live before this was filtered: a host received
        'End Flow.exec_in' as a GTText value.
        """
        bridge = ExecutionBridge()
        bridge.install()
        before = len(event_manager.payloads())
        bridge._on_parameter_value(
            ParameterValueUpdateEvent(
                node_name="End Flow",
                parameter_name="exec_in",
                data_type=CONTROL_PARAM_TYPE,
                value=None,
            )
        )
        assert len(event_manager.payloads()) == before, "execution wiring must not reach a host"

    def test_flow_resolved_reports_the_terminal_node_and_no_values(self, event_manager: FakeEventManager) -> None:
        """Values are read on demand, not gathered inside a callback.

        The engine asks listeners to stay cheap, and `end_node_name` is whichever node
        control flow ended on, which is often not a declared output node. Carrying its
        values here would give "outputs" two meanings.
        """
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_flow_resolved(
            ControlFlowResolvedEvent(end_node_name="Execute Python_1", parameter_output_values={"x": 1})
        )
        payload = event_manager.payloads()[-1]
        assert isinstance(payload, NukeExecutionStateEvent)
        assert payload.state == ExecutionState.COMPLETED
        assert payload.terminal_node == "Execute Python_1"
        assert not hasattr(payload, "outputs")

    def test_flow_resolved_never_reports_failed_or_succeeded(self, event_manager: FakeEventManager) -> None:
        """ControlFlowResolvedEvent fires on both a clean run and an errored one.

        The engine gives this callback no status to report, so it must not guess one,
        including by inferring from a NodeErrorEvent seen earlier in the same run.
        """
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_node_error(NodeErrorEvent(node_name="Blur", error_message="kaboom"))
        bridge._on_flow_resolved(ControlFlowResolvedEvent(end_node_name="Blur", parameter_output_values={}))
        payload = event_manager.payloads()[-1]
        assert payload.state not in {ExecutionState.FAILED, "succeeded"}
        assert payload.state == ExecutionState.COMPLETED

    def test_flow_cancelled_reports_cancelled(self, event_manager: FakeEventManager) -> None:
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_flow_cancelled(ControlFlowCancelledEvent(result_details="user stopped it"))
        payload = event_manager.payloads()[-1]
        assert payload.state == ExecutionState.CANCELLED
        assert "user stopped it" in payload.detail

    def test_notifications_are_wrapped_in_app_events(self, event_manager: FakeEventManager) -> None:
        """AppEvent via put_event is the only path that reaches IPC.

        broadcast_app_event notifies in-process listeners only and never reaches a host.
        """
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_node_start(NodeStartProcessEvent(node_name="Blur"))
        assert all(isinstance(event, AppEvent) for event in event_manager.emitted)
