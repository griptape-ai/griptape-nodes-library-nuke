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

from nuke_host_api import execution_bridge
from nuke_host_api.events import (
    NukeExecutionNodesEvent,
    NukeExecutionStateEvent,
    NukeNodeProgressEvent,
    NukeNodeStateEvent,
    NukeParameterValueEvent,
)
from nuke_host_api.execution_bridge import PROGRESS_BAR_UI_OPTION, STATUS_PARAMETER, ExecutionBridge
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

    def test_install_subscribes_the_events_that_mark_a_start_and_carry_progress(
        self, event_manager: FakeEventManager
    ) -> None:
        ExecutionBridge().install()
        assert {CurrentDataNodeEvent, CurrentControlNodeEvent, AlterElementEvent} <= event_manager.listeners.keys()

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
    def _leave_it_uninstalled(self, event_manager: FakeEventManager) -> Iterator[None]:  # noqa: ARG002
        """The process bridge is shared, so a test that installs it must put it back.

        Depends on ``event_manager`` so this finalizer runs before that fixture's
        monkeypatch is undone. Without it, uninstall reaches the real engine and boots it.
        """
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

    @pytest.mark.parametrize("event_type", [CurrentDataNodeEvent, CurrentControlNodeEvent])
    def test_a_current_node_event_becomes_running(self, event_manager: FakeEventManager, event_type: type) -> None:
        """The engine never emits NodeStartProcessEvent, so these are the only start signal."""
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_node_start(event_type(node_name="Blur"))
        payload = event_manager.payloads()[-1]
        assert payload == NukeNodeStateEvent(node_name="Blur", state=NodeState.RUNNING)

    def test_a_control_node_reported_twice_is_running_once(self, event_manager: FakeEventManager) -> None:
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_node_start(CurrentControlNodeEvent(node_name="Blur"))
        bridge._on_node_start(CurrentDataNodeEvent(node_name="Blur"))
        assert event_manager.payloads() == [NukeNodeStateEvent(node_name="Blur", state=NodeState.RUNNING)]

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
                value=ImageUrlArtifact("/workspace/outputs/a.png"),
            )
        )
        payload = event_manager.payloads()[-1]
        assert isinstance(payload, NukeParameterValueEvent)
        assert payload.value["value_type"] == ValueType.IMAGE
        assert payload.value["value"] == {
            "path": "/workspace/outputs/a.png",
            "format": "png",
            "first": None,
            "last": None,
        }

    def test_a_value_with_no_host_form_is_not_forwarded(self, event_manager: FakeEventManager) -> None:
        """A bulk read reports it as unavailable with a reason; a notification has nowhere to put one."""
        bridge = ExecutionBridge()
        bridge.install()
        before = len(event_manager.payloads())
        bridge._on_parameter_value(
            ParameterValueUpdateEvent(
                node_name="Read",
                parameter_name="image",
                data_type="ImageUrlArtifact",
                value=ImageUrlArtifact("https://cdn.example.com/a.png"),
            )
        )
        assert len(event_manager.payloads()) == before

    def test_a_control_flow_parameter_update_is_not_forwarded(self, event_manager: FakeEventManager) -> None:
        """The engine streams a value update for exec_in like any other parameter.

        Forwarding it would contradict describe_workflow, which never lists control parameters,
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

    def test_involved_nodes_are_forwarded_as_the_progress_denominator(self, event_manager: FakeEventManager) -> None:
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_involved_nodes(InvolvedNodesEvent(involved_nodes=["Start Flow", "Blur", "End Flow"]))
        payload = event_manager.payloads()[-1]
        assert isinstance(payload, NukeExecutionNodesEvent)
        assert payload.involved_nodes == ["Start Flow", "Blur", "End Flow"]

    def test_involved_nodes_forwards_an_empty_set_too(self, event_manager: FakeEventManager) -> None:
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_involved_nodes(InvolvedNodesEvent(involved_nodes=[]))
        payload = event_manager.payloads()[-1]
        assert isinstance(payload, NukeExecutionNodesEvent)
        assert payload.involved_nodes == []

    def test_notifications_are_wrapped_in_app_events(self, event_manager: FakeEventManager) -> None:
        """AppEvent via put_event is the only path that reaches IPC.

        broadcast_app_event notifies in-process listeners only and never reaches a host.
        """
        bridge = ExecutionBridge()
        bridge.install()
        bridge._on_node_start(NodeStartProcessEvent(node_name="Blur"))
        assert all(isinstance(event, AppEvent) for event in event_manager.emitted)


def _altered(
    node_name: str,
    parameter_name: str,
    value: Any,
    *,
    progress_bar: bool = False,
    modification_type: str = "set",
) -> AlterElementEvent:
    return AlterElementEvent(
        element_details={
            "node_name": node_name,
            "parameter_name": parameter_name,
            "value": value,
            "ui_options": {PROGRESS_BAR_UI_OPTION: True} if progress_bar else {},
            "modification_type": modification_type,
        }
    )


class TestNodeProgress:
    @pytest.fixture
    def bridge(self, event_manager: FakeEventManager) -> ExecutionBridge:  # noqa: ARG002
        bridge = ExecutionBridge()
        bridge.install()
        return bridge

    @staticmethod
    def progress_events(event_manager: FakeEventManager) -> list[NukeNodeProgressEvent]:
        return [payload for payload in event_manager.payloads() if isinstance(payload, NukeNodeProgressEvent)]

    def test_a_progress_bar_value_is_reported_as_a_fraction(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager
    ) -> None:
        bridge._on_node_start(NodeStartProcessEvent(node_name="Upscale"))
        bridge._on_element_altered(_altered("Upscale", "progress", 0.25, progress_bar=True))

        assert self.progress_events(event_manager) == [
            NukeNodeProgressEvent(node_name="Upscale", progress=0.25, message="")
        ]

    def test_a_status_string_is_reported_with_no_known_end(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager
    ) -> None:
        bridge._on_node_start(NodeStartProcessEvent(node_name="Flux"))
        bridge._on_element_altered(_altered("Flux", STATUS_PARAMETER, "RUNNING"))

        assert self.progress_events(event_manager) == [
            NukeNodeProgressEvent(node_name="Flux", progress=None, message="RUNNING")
        ]

    def test_a_status_change_keeps_the_known_fraction(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager
    ) -> None:
        bridge._on_node_start(NodeStartProcessEvent(node_name="Upscale"))
        bridge._on_element_altered(_altered("Upscale", "progress", 0.5, progress_bar=True))
        bridge._on_element_altered(_altered("Upscale", STATUS_PARAMETER, "RUNNING"))

        assert self.progress_events(event_manager)[-1] == NukeNodeProgressEvent(
            node_name="Upscale", progress=0.5, message="RUNNING"
        )

    def test_a_fraction_outside_the_unit_range_is_clamped(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager
    ) -> None:
        bridge._on_node_start(NodeStartProcessEvent(node_name="Upscale"))
        bridge._on_element_altered(_altered("Upscale", "progress", 1.5, progress_bar=True))
        bridge._on_element_altered(_altered("Upscale", "progress", -1, progress_bar=True))

        assert [event.progress for event in self.progress_events(event_manager)] == [1.0, 0.0]

    def test_a_non_numeric_progress_bar_value_is_ignored(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager
    ) -> None:
        bridge._on_node_start(NodeStartProcessEvent(node_name="Upscale"))
        bridge._on_element_altered(_altered("Upscale", "progress", "half", progress_bar=True))
        bridge._on_element_altered(_altered("Upscale", "progress", True, progress_bar=True))  # noqa: FBT003

        assert self.progress_events(event_manager) == []

    def test_an_ordinary_parameter_is_not_progress(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager
    ) -> None:
        bridge._on_node_start(NodeStartProcessEvent(node_name="Upscale"))
        bridge._on_element_altered(_altered("Upscale", "scale", 0.5))

        assert self.progress_events(event_manager) == []

    def test_a_node_that_is_not_running_reports_no_progress(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager
    ) -> None:
        bridge._on_element_altered(_altered("Upscale", "progress", 0.5, progress_bar=True))

        assert self.progress_events(event_manager) == []

    def test_a_deleted_value_is_not_progress(self, bridge: ExecutionBridge, event_manager: FakeEventManager) -> None:
        """Clearing outputs emits the stored value, which says nothing about this run."""
        bridge._on_node_start(NodeStartProcessEvent(node_name="Upscale"))
        bridge._on_element_altered(_altered("Upscale", "progress", 0.9, progress_bar=True, modification_type="deleted"))

        assert self.progress_events(event_manager) == []

    @pytest.mark.parametrize(
        ("handler", "event"),
        [
            (
                "_on_node_resolved",
                NodeResolvedEvent(node_name="Upscale", node_type="Upscale", parameter_output_values={}),
            ),
            ("_on_node_unresolved", NodeUnresolvedEvent(node_name="Upscale")),
            ("_on_node_finish", NodeFinishProcessEvent(node_name="Upscale")),
            ("_on_node_error", NodeErrorEvent(node_name="Upscale", error_message="kaboom")),
        ],
    )
    def test_progress_stops_once_the_node_leaves_running(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager, handler: str, event: Any
    ) -> None:
        bridge._on_node_start(NodeStartProcessEvent(node_name="Upscale"))
        getattr(bridge, handler)(event)
        bridge._on_element_altered(_altered("Upscale", "progress", 0.5, progress_bar=True))

        assert self.progress_events(event_manager) == []

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_progress_bar_value_is_ignored(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager, value: float
    ) -> None:
        bridge._on_node_start(NodeStartProcessEvent(node_name="Upscale"))
        bridge._on_element_altered(_altered("Upscale", "progress", value, progress_bar=True))

        assert self.progress_events(event_manager) == []

    def test_a_non_string_status_is_reported_as_an_empty_message(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager
    ) -> None:
        bridge._on_node_start(NodeStartProcessEvent(node_name="Flux"))
        bridge._on_element_altered(_altered("Flux", STATUS_PARAMETER, 3))

        assert self.progress_events(event_manager) == [
            NukeNodeProgressEvent(node_name="Flux", progress=None, message="")
        ]

    @pytest.mark.parametrize(
        "end_flow",
        [
            lambda bridge: bridge._on_flow_cancelled(ControlFlowCancelledEvent(result_details="stopped")),
            lambda bridge: bridge._on_flow_resolved(
                ControlFlowResolvedEvent(end_node_name="End Flow", parameter_output_values={})
            ),
        ],
        ids=["cancelled", "resolved"],
    )
    def test_the_end_of_the_flow_ends_progress_and_the_next_run_starts_fresh(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager, end_flow: Any
    ) -> None:
        """Cancel emits no per-node events and loop start nodes never resolve."""
        bridge._on_node_start(NodeStartProcessEvent(node_name="Loop Start"))
        bridge._on_element_altered(_altered("Loop Start", "progress", 0.5, progress_bar=True))
        end_flow(bridge)
        bridge._on_element_altered(_altered("Loop Start", "progress", 0.75, progress_bar=True))
        bridge._on_node_start(NodeStartProcessEvent(node_name="Loop Start"))

        assert [event.progress for event in self.progress_events(event_manager)] == [0.5]
        running = [
            payload
            for payload in event_manager.payloads()
            if isinstance(payload, NukeNodeStateEvent) and payload.state == NodeState.RUNNING
        ]
        assert len(running) == 2

    def test_a_rerun_starts_from_an_empty_snapshot(
        self, bridge: ExecutionBridge, event_manager: FakeEventManager
    ) -> None:
        bridge._on_node_start(NodeStartProcessEvent(node_name="Upscale"))
        bridge._on_element_altered(_altered("Upscale", "progress", 0.5, progress_bar=True))
        bridge._on_node_resolved(
            NodeResolvedEvent(node_name="Upscale", node_type="Upscale", parameter_output_values={})
        )
        bridge._on_node_start(NodeStartProcessEvent(node_name="Upscale"))
        bridge._on_element_altered(_altered("Upscale", STATUS_PARAMETER, "QUEUED"))

        assert self.progress_events(event_manager)[-1] == NukeNodeProgressEvent(
            node_name="Upscale", progress=None, message="QUEUED"
        )
