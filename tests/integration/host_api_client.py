"""Stdlib host client for the Nuke host API, used by the integration smoke tests.

This is a test harness, not a shipped reference client, but it is the smallest complete
implementation of what a Nuke plugin must do and the transport half is worth porting
verbatim:

  discover()          read engines.json, resolve a socket path, treat its existence as liveness
  HostClient.request  send one request, pump frames until the matching request_id returns
  HostClient.drain    collect pushed notifications while sending nothing

Stdlib only (socket, json, uuid), so the smoke tests add no dependency and nothing here can
rely on something a C++ plugin could not do.

The pump is the part a request-response helper gets wrong. Results and notifications share
one socket, so a client that reads until it finds its reply and discards the rest silently
loses every event.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPLY_TOPIC = "nuke-smoke/reply"
DEFAULT_TIMEOUT_S = 60.0


def _xdg_data_home() -> Path:
    override = os.environ.get("XDG_DATA_HOME")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share"


def engines_registry_path() -> Path:
    return _xdg_data_home() / "griptape_nodes" / "engines.json"


def socket_path_for(engine_id: str) -> str:
    """Return the platform socket path for an engine id."""
    if sys.platform == "win32":
        return f"\\\\.\\pipe\\griptape_nodes_{engine_id}"
    return str(_xdg_data_home() / "griptape_nodes" / "ipc" / f"{engine_id}.sock")


@dataclass
class Engine:
    """One registry entry, plus where to reach it."""

    id: str
    name: str
    socket_path: str
    is_default: bool = False

    @property
    def running(self) -> bool:
        """The socket exists only while that engine runs with local_socket enabled."""
        return Path(self.socket_path).exists()


def discover() -> list[Engine]:
    """Return every registered engine, running or not.

    Off the wire entirely. A host has no connection yet, so nothing here may issue a request
    to find out where to connect.
    """
    registry = engines_registry_path()
    if not registry.exists():
        return []
    try:
        data = json.loads(registry.read_text())
    except (OSError, json.JSONDecodeError):
        return []

    default_id = data.get("default_engine_id")
    engines = []
    for entry in data.get("engines", []):
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        engine_id = str(entry["id"])
        engines.append(
            Engine(
                id=engine_id,
                name=str(entry.get("name") or engine_id),
                socket_path=socket_path_for(engine_id),
                is_default=engine_id == default_id,
            )
        )
    return engines


def running_engine() -> Engine | None:
    """Return a running engine, preferring the registry's default."""
    live = [engine for engine in discover() if engine.running]
    if not live:
        return None
    return next((engine for engine in live if engine.is_default), live[0])


@dataclass
class Notification:
    """One pushed host event."""

    type: str
    body: dict[str, Any]


@dataclass
class HostClient:
    """Request/reply plus a notification stream over one local socket."""

    socket_path: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    notifications: list[Notification] = field(default_factory=list)
    _sock: socket.socket | None = None
    _buffer: bytes = b""

    def __enter__(self) -> HostClient:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout_s)
        self._sock.connect(self.socket_path)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def request(self, request_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one request and return the reply payload whose request_id matches."""
        request_id = uuid.uuid4().hex
        self._send(
            {
                "payload": {
                    "event_type": "EventRequest",
                    "request_type": request_type,
                    "request": payload or {},
                    "request_id": request_id,
                    "response_topic": REPLY_TOPIC,
                }
            }
        )
        return self._pump(until_request_id=request_id)

    def drain(self, seconds: float) -> list[Notification]:
        """Collect notifications for a while, sending nothing.

        A pass here cannot be explained by polling, which is the point: it exercises the push
        path rather than the request path.
        """
        started = time.monotonic()
        first_new = len(self.notifications)
        while True:
            remaining = seconds - (time.monotonic() - started)
            if remaining <= 0:
                break
            try:
                self._read_frame(timeout_s=remaining)
            except TimeoutError:
                break
        return self.notifications[first_new:]

    def of_type(self, payload_type: str) -> list[Notification]:
        return [event for event in self.notifications if event.type == payload_type]

    def _send(self, message: dict[str, Any]) -> None:
        if self._sock is None:
            msg = "client is not connected"
            raise RuntimeError(msg)
        self._sock.sendall((json.dumps(message) + "\n").encode())

    def _read_frame(self, timeout_s: float) -> dict[str, Any] | None:
        """Read one newline-delimited frame. Records notifications, returns reply payloads."""
        if self._sock is None:
            msg = "client is not connected"
            raise RuntimeError(msg)
        if timeout_s <= 0:
            raise TimeoutError

        self._sock.settimeout(timeout_s)
        while b"\n" not in self._buffer:
            chunk = self._sock.recv(65536)
            if not chunk:
                msg = "engine closed the connection"
                raise ConnectionError(msg)
            self._buffer += chunk

        line, _, self._buffer = self._buffer.partition(b"\n")
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            # A frame that will not parse is not worth killing the pump for. The awaited
            # reply may still be behind it.
            return None
        if not isinstance(frame, dict):
            return None

        payload = frame.get("payload") or {}
        if frame.get("type") == "app_event" or payload.get("event_type") == "AppEvent":
            payload_type = str(payload.get("payload_type") or "")
            # Every outbound frame reaches every client on this transport, so anything that
            # is not this protocol's is someone else's traffic.
            if payload_type.startswith("Nuke"):
                self.notifications.append(Notification(type=payload_type, body=payload.get("payload") or {}))
            return None
        return payload

    def _pump(self, until_request_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                msg = f"timed out waiting for a reply to {until_request_id}"
                raise TimeoutError(msg)
            payload = self._read_frame(timeout_s=remaining)
            if payload is not None and payload.get("request_id") == until_request_id:
                return payload


def succeeded(reply: dict[str, Any]) -> bool:
    return reply.get("event_type") == "EventResultSuccess"


def result_of(reply: dict[str, Any]) -> dict[str, Any]:
    body = reply.get("result")
    return body if isinstance(body, dict) else {}


def detail_of(reply: dict[str, Any]) -> str:
    """Pull the human-readable message out of the nested result_details shape."""
    details = result_of(reply).get("result_details")
    if isinstance(details, dict):
        entries = details.get("result_details") or []
        if entries:
            return "; ".join(str(entry.get("message", entry)) for entry in entries)
    return str(details)
