"""Tests for the smoke-test host client.

The harness has real logic, and two pieces of it are exactly what a plugin gets wrong:
resolving an engine without a connection, and deciding which frames off a shared socket
belong to this host. Both are pure, so both are tested here rather than only when an engine
happens to be running.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from tests.integration import host_api_client
from tests.integration.host_api_client import HostClient, detail_of, result_of, succeeded

if TYPE_CHECKING:
    import pathlib

REGISTRY = {
    "engines": [
        {"id": "aaa-111", "name": "honest-red-ant", "created_at": "2026-08-24T22:02:19.397484+00:00"},
        {"id": "bbb-222", "name": "quiet-blue-fox", "created_at": "2026-08-25T09:00:00.000000+00:00"},
    ],
    "default_engine_id": "bbb-222",
}


@pytest.fixture
def data_home(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    root = tmp_path / "griptape_nodes"
    (root / "ipc").mkdir(parents=True)
    (root / "engines.json").write_text(json.dumps(REGISTRY))
    return root


class TestDiscovery:
    def test_every_registry_entry_resolves_to_a_socket_path(self, data_home: pathlib.Path) -> None:
        assert data_home.exists()
        engines = host_api_client.discover()
        assert [engine.id for engine in engines] == ["aaa-111", "bbb-222"]
        assert [engine.name for engine in engines] == ["honest-red-ant", "quiet-blue-fox"]
        assert engines[0].socket_path.endswith("griptape_nodes/ipc/aaa-111.sock")

    def test_only_the_registrys_default_is_flagged_default(self, data_home: pathlib.Path) -> None:
        assert data_home.exists()
        flagged = [engine.id for engine in host_api_client.discover() if engine.is_default]
        assert flagged == ["bbb-222"]

    def test_an_engine_is_running_only_while_its_socket_exists(self, data_home: pathlib.Path) -> None:
        """Socket existence is the whole liveness test, so it has to be exactly that."""
        engines = {engine.id: engine for engine in host_api_client.discover()}
        assert not engines["aaa-111"].running

        (data_home / "ipc" / "aaa-111.sock").touch()
        assert host_api_client.discover()[0].running

    def test_the_default_engine_is_preferred_when_several_are_running(self, data_home: pathlib.Path) -> None:
        (data_home / "ipc" / "aaa-111.sock").touch()
        (data_home / "ipc" / "bbb-222.sock").touch()
        chosen = host_api_client.running_engine()
        assert chosen is not None
        assert chosen.id == "bbb-222"

    def test_no_running_engine_is_reported_when_no_socket_exists(self, data_home: pathlib.Path) -> None:
        assert data_home.exists()
        assert host_api_client.running_engine() is None

    def test_a_missing_registry_is_not_an_error(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A host asking before the engine has ever run must get an empty list, not a crash."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert host_api_client.discover() == []
        assert host_api_client.running_engine() is None

    def test_an_unparseable_registry_is_not_an_error(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        registry = tmp_path / "griptape_nodes" / "engines.json"
        registry.parent.mkdir(parents=True)
        registry.write_text("{ this is not json")
        assert host_api_client.discover() == []

    def test_an_entry_with_no_id_is_skipped(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        registry = tmp_path / "griptape_nodes" / "engines.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(json.dumps({"engines": [{"name": "nameless"}, {"id": "ok-1"}]}))
        assert [engine.id for engine in host_api_client.discover()] == ["ok-1"]


class FakeSocket:
    """Serves canned frames as newline-delimited bytes, then times out.

    ``chunk_size`` exists to drive a frame across several reads, since newline framing means
    a JSON object can straddle two recv calls on a real socket.
    """

    def __init__(self, frames: list[Any], chunk_size: int = 65536) -> None:
        self.sent: list[dict] = []
        self.chunk_size = chunk_size
        payload = "".join(frame if isinstance(frame, str) else json.dumps(frame) for frame in frames)
        self._to_read = payload.encode()

    def settimeout(self, _timeout: float) -> None:
        return

    def sendall(self, data: bytes) -> None:
        self.sent.append(json.loads(data.decode()))

    def recv(self, size: int) -> bytes:
        if not self._to_read:
            raise TimeoutError
        take = min(size, self.chunk_size)
        chunk, self._to_read = self._to_read[:take], self._to_read[take:]
        return chunk

    def close(self) -> None:
        return


def _client(frames: list[Any], chunk_size: int = 65536) -> tuple[HostClient, FakeSocket]:
    sock = FakeSocket(frames, chunk_size=chunk_size)
    client = HostClient(socket_path="/unused", timeout_s=1.0)
    client._sock = sock  # type: ignore[assignment]  # noqa: SLF001
    return client, sock


def _reply(request_id: str, result_type: str = "NukeConnectResultSuccess", **result: Any) -> str:
    frame = {
        "type": "success_result",
        "topic": host_api_client.REPLY_TOPIC,
        "payload": {
            "event_type": "EventResultSuccess",
            "request_id": request_id,
            "result_type": result_type,
            "result": result,
        },
    }
    return json.dumps(frame) + "\n"


def _app_event(payload_type: str, **body: Any) -> str:
    frame = {"type": "app_event", "topic": "x/response", "payload": {"payload_type": payload_type, "payload": body}}
    return json.dumps(frame) + "\n"


class TestFrameHandling:
    def test_a_reply_is_matched_by_request_id_and_notifications_are_kept(self) -> None:
        """Replies and notifications share one socket.

        A client that returns on the first frame it reads, or that discards anything that is
        not its reply, silently loses every event. This is the bug the pump exists to avoid,
        so the reply arrives behind two notifications here.
        """
        client, _ = _client(
            [
                _app_event("NukeNodeStateEvent", node_name="Start Flow", state="running"),
                _app_event("NukeParameterValueEvent", node_name="End Flow", parameter_name="summary"),
                _reply("abc123", engine_version="1.2.3"),
            ]
        )
        payload = client._pump(until_request_id="abc123")  # noqa: SLF001

        assert payload["result"]["engine_version"] == "1.2.3"
        assert [event.type for event in client.notifications] == [
            "NukeNodeStateEvent",
            "NukeParameterValueEvent",
        ]

    def test_a_request_is_sent_with_the_envelope_the_engine_expects(self) -> None:
        """The envelope is the part a mocked suite cannot check and a plugin must get exactly right."""
        client, sock = _client([])
        with pytest.raises(TimeoutError):
            client.request("NukeConnectRequest", {"client_protocol_versions": [1]})

        assert len(sock.sent) == 1
        payload = sock.sent[0]["payload"]
        assert payload["event_type"] == "EventRequest"
        assert payload["request_type"] == "NukeConnectRequest"
        assert payload["request"] == {"client_protocol_versions": [1]}
        assert payload["response_topic"] == host_api_client.REPLY_TOPIC
        assert payload["request_id"]

    def test_a_reply_for_a_different_request_is_discarded(self) -> None:
        client, _ = _client([_reply("someone-else"), _reply("mine")])
        payload = client._pump(until_request_id="mine")  # noqa: SLF001
        assert payload["request_id"] == "mine"

    def test_an_event_from_another_library_is_not_recorded(self) -> None:
        """Every outbound frame reaches every client, so filtering is the host's job."""
        client, _ = _client(
            [
                _app_event("SomeOtherLibraryEvent", detail="not mine"),
                _app_event("NukeNodeStateEvent", node_name="N", state="resolved"),
                _reply("mine"),
            ]
        )
        client._pump(until_request_id="mine")  # noqa: SLF001
        assert [event.type for event in client.notifications] == ["NukeNodeStateEvent"]

    def test_an_unparseable_frame_does_not_kill_the_pump(self) -> None:
        """The awaited reply may still be behind a frame that will not parse."""
        client, _ = _client(["{ not json\n", _reply("mine")])
        assert client._pump(until_request_id="mine")["request_id"] == "mine"  # noqa: SLF001

    def test_a_frame_split_across_reads_is_reassembled(self) -> None:
        """Newline-delimited framing means a JSON object can straddle two recv calls."""
        client, _ = _client([_reply("mine", engine_version="9.9.9")], chunk_size=1)
        payload = client._pump(until_request_id="mine")  # noqa: SLF001
        assert payload["result"]["engine_version"] == "9.9.9"

    def test_drain_returns_only_newly_arrived_notifications(self) -> None:
        client, _ = _client(
            [
                _app_event("NukeNodeStateEvent", node_name="A", state="running"),
                _app_event("NukeNodeStateEvent", node_name="B", state="resolved"),
            ]
        )
        arrived = client.drain(seconds=0.5)
        assert [event.body["node_name"] for event in arrived] == ["A", "B"]
        assert client.drain(seconds=0.05) == []

    def test_a_closed_connection_is_reported_rather_than_hanging(self) -> None:
        client, sock = _client([])
        sock.recv = lambda _size: b""  # type: ignore[method-assign]
        with pytest.raises(ConnectionError):
            client._pump(until_request_id="mine")  # noqa: SLF001

    def test_of_type_selects_one_notification_kind(self) -> None:
        client, _ = _client(
            [
                _app_event("NukeNodeStateEvent", node_name="A", state="running"),
                _app_event("NukeExecutionStateEvent", state="completed"),
                _reply("mine"),
            ]
        )
        client._pump(until_request_id="mine")  # noqa: SLF001
        assert [event.body["state"] for event in client.of_type("NukeExecutionStateEvent")] == ["completed"]


class TestReplyHelpers:
    def test_success_is_read_from_the_event_type(self) -> None:
        assert succeeded({"event_type": "EventResultSuccess"})
        assert not succeeded({"event_type": "EventResultFailure"})
        assert not succeeded({})

    def test_a_missing_result_reads_as_an_empty_mapping(self) -> None:
        assert result_of({}) == {}
        assert result_of({"result": "not a dict"}) == {}

    def test_the_artist_facing_message_is_pulled_out_of_the_nested_shape(self) -> None:
        reply = {"result": {"result_details": {"result_details": [{"level": 10, "message": "no such workflow"}]}}}
        assert detail_of(reply) == "no such workflow"
