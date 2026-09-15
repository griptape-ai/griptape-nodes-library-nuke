from __future__ import annotations

from typing import Any

import pytest
from griptape_nodes.retained_mode.events.base_events import AppEvent

from nuke_host_api import notify
from nuke_host_api.events import NukeHostDisconnectEvent
from nuke_host_api.protocol import DisconnectCause


class FakeEventManager:
    def __init__(self) -> None:
        self.emitted: list[Any] = []

    def put_event(self, event: Any) -> None:
        self.emitted.append(event)


class FakeEngine:
    def __init__(self, event_manager: FakeEventManager) -> None:
        self._event_manager = event_manager

    def EventManager(self) -> FakeEventManager:  # noqa: N802
        return self._event_manager


@pytest.fixture
def event_manager(monkeypatch: pytest.MonkeyPatch) -> FakeEventManager:
    manager = FakeEventManager()
    monkeypatch.setattr(notify, "GriptapeNodes", FakeEngine(manager))
    return manager


def test_publishing_wraps_the_payload_in_an_app_event(event_manager: FakeEventManager) -> None:
    """``put_event(AppEvent(...))`` is the only path that reaches a host over IPC.

    ``broadcast_app_event`` notifies in-process listeners and nothing on a socket, so a
    payload sent that way is published to no host and raises nothing.
    """
    payload = NukeHostDisconnectEvent(
        client_name="Nuke shot_040",
        cause=DisconnectCause.CLAIM_TAKEN,
        reason="Nuke shot_112 took this engine.",
        replaced_by="Nuke shot_112",
    )

    notify.publish(payload)

    assert len(event_manager.emitted) == 1
    event = event_manager.emitted[0]
    assert isinstance(event, AppEvent)
    assert event.payload is payload
