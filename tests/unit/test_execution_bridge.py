"""Tests for the outbound event bridge.

Two properties matter. Subscriptions must be symmetric, because a bridge that installs
more listeners than it removes duplicates every notification a host receives. And values
must be normalized before they leave, because the live path is where a host would
otherwise meet raw engine artifacts.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

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
from nuke_nodes import nuke_library_advanced
from nuke_nodes.nuke_library_advanced import NukeLibraryAdvanced

if TYPE_CHECKING:
    from collections.abc import Iterator


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


class TestProcessBridgeLifecycle:
    """The bridge's subscription is engine-global, so when it installs is a real decision."""

    @pytest.fixture(autouse=True)
    def _leave_it_uninstalled(self) -> Iterator[None]:
        """The process bridge is shared, so a test that installs it must put it back."""
        yield
        execution_bridge.uninstall()

    def test_loading_the_library_does_not_subscribe(
        self, event_manager: FakeEventManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of the latch.

        An engine that merely has this library installed, with no transport enabled for a
        host to arrive on, must not pay to translate and re-emit every execution event it
        runs. So the real load hook is driven here, and nothing in it may subscribe.
        """
        registered: list[object] = []

        class FakeLibraryManager:
            def on_register_event_handler(self, **kwargs: Any) -> None:
                registered.append(kwargs["request_type"])

        class FakeGriptapeNodes:
            @staticmethod
            def LibraryManager() -> FakeLibraryManager:  # noqa: N802
                return FakeLibraryManager()

        monkeypatch.setattr(nuke_library_advanced, "GriptapeNodes", FakeGriptapeNodes)
        library_data = SimpleNamespace(name="Nuke Nodes Library")

        NukeLibraryAdvanced().after_library_nodes_loaded(library_data, None)  # type: ignore[arg-type]

        assert registered, "the load hook must still register the publish handler"
        assert not execution_bridge.is_installed()
        assert not any(event_manager.listeners.values())

    def test_a_host_connecting_subscribes(self, event_manager: FakeEventManager) -> None:
        execution_bridge.ensure_installed()

        assert execution_bridge.is_installed()
        assert any(event_manager.listeners.values())

    def test_repeated_connects_do_not_duplicate_listeners(self, event_manager: FakeEventManager) -> None:
        """A host may connect repeatedly, and each reconnect must not add another listener set.

        Duplicate subscriptions are the failure this guards: a host would receive every
        notification twice, then three times.
        """
        execution_bridge.ensure_installed()
        after_first = {event: set(callbacks) for event, callbacks in event_manager.listeners.items()}

        execution_bridge.ensure_installed()
        execution_bridge.ensure_installed()

        assert {event: set(callbacks) for event, callbacks in event_manager.listeners.items()} == after_first

    def test_library_unload_removes_every_listener(self, event_manager: FakeEventManager) -> None:
        execution_bridge.ensure_installed()
        execution_bridge.uninstall()

        assert not execution_bridge.is_installed()
        assert not any(event_manager.listeners.values()), "a listener outlived the bridge that added it"

    def test_unload_without_any_host_having_connected_is_a_no_op(self, event_manager: FakeEventManager) -> None:
        """Library unload calls this unconditionally, including when no host ever connected."""
        execution_bridge.uninstall()
        assert not any(event_manager.listeners.values())


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
