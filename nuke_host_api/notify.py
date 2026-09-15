"""Publish a host notification on the only path that reaches a host."""

from __future__ import annotations

from typing import TYPE_CHECKING

from griptape_nodes.retained_mode.events.base_events import AppEvent
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

if TYPE_CHECKING:
    from griptape_nodes.retained_mode.events.base_events import AppPayload


def publish(payload: AppPayload) -> None:
    """``broadcast_app_event`` reaches in-process listeners only, so IPC needs ``put_event``."""
    GriptapeNodes.EventManager().put_event(AppEvent(payload=payload))
