"""Tests for version negotiation and opening the event stream."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from griptape_nodes.retained_mode.events.app_events import GetEngineVersionRequest

from nuke_host_api import execution_bridge, session
from nuke_host_api.events import (
    NukeConnectRequest,
    NukeConnectResultFailure,
    NukeConnectResultSuccess,
    NukeSessionRevokedEvent,
)
from nuke_host_api.handlers import handle_connect
from nuke_host_api.protocol import PROTOCOL_VERSION, VALUE_TYPES
from tests.unit.host_api_fakes import ENGINE_VERSION, FakeEngine, use_engine

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _authorized_session() -> Iterator[None]:
    """This file exercises the real lease, so the shared bypass in conftest.py must not apply.

    Redefining the fixture under the same name shadows the conftest.py one for every test in
    this module. ``handle_connect`` never reaches ``session.authorize`` anyway, since
    NukeConnectRequest is exempt from the token check, but ``session.claim`` is real here and
    must start and end each test with an empty lease so tests cannot see each other's claims.
    """
    session.reset()
    yield
    session.reset()


@pytest.fixture(autouse=True)
def _fake_engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    return use_engine(monkeypatch, {GetEngineVersionRequest: ENGINE_VERSION})


@pytest.fixture(autouse=True)
def _record_bridge_installs(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Stub the real install, which would subscribe this process to the engine's feed."""
    calls: list[bool] = []
    monkeypatch.setattr(execution_bridge, "ensure_installed", lambda: calls.append(True))
    return calls


def _connect(
    *,
    client_protocol_versions: list[int] | None = None,
    client_id: str = "nuke-1",
    client_name: str = "Nuke 16.0v7",
    force: bool = False,
) -> NukeConnectRequest:
    return NukeConnectRequest(
        client_protocol_versions=[PROTOCOL_VERSION] if client_protocol_versions is None else client_protocol_versions,
        client_id=client_id,
        client_name=client_name,
        force=force,
    )


def test_connecting_installs_the_event_bridge(_record_bridge_installs: list[bool]) -> None:
    """Notifications begin at connect, so a successful connect must subscribe.

    Forgetting this is silent: every request still succeeds and no event ever arrives.
    """
    result = handle_connect(_connect())
    assert isinstance(result, NukeConnectResultSuccess)
    assert _record_bridge_installs == [True]


def test_a_refused_connect_does_not_install_the_event_bridge(_record_bridge_installs: list[bool]) -> None:
    """A host that could not agree a version must not leave the engine paying for a feed."""
    result = handle_connect(_connect(client_protocol_versions=[99]))
    assert isinstance(result, NukeConnectResultFailure)
    assert _record_bridge_installs == []


def test_a_matching_version_connects() -> None:
    result = handle_connect(_connect())
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.protocol_version == PROTOCOL_VERSION
    assert result.value_types == list(VALUE_TYPES)


def test_the_event_topic_is_handed_over() -> None:
    """A host cannot derive this, so failing to return it strands notifications."""
    result = handle_connect(_connect())
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.event_topic == "sessions/session-abc/response"


def test_both_versions_are_reported() -> None:
    """A support ticket names an engine and a library; a host cannot look either one up."""
    result = handle_connect(_connect())
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.engine_version == "0.97.0"
    assert result.library_version == "0.3.0"


def test_an_empty_offer_assumes_the_current_version() -> None:
    """Keeps a bare connectivity check working."""
    result = handle_connect(_connect(client_protocol_versions=[]))
    assert isinstance(result, NukeConnectResultSuccess)


def test_an_unsupported_version_is_refused_with_the_window() -> None:
    result = handle_connect(_connect(client_protocol_versions=[99]))
    assert isinstance(result, NukeConnectResultFailure)
    assert result.supported_protocol_versions
    assert "99" in str(result.result_details)


def test_the_highest_mutual_version_wins() -> None:
    result = handle_connect(_connect(client_protocol_versions=[99, PROTOCOL_VERSION]))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.protocol_version == PROTOCOL_VERSION


class TestSessionLease:
    """Connect is also where a host claims, renews, loses, or forces this engine's lease."""

    def test_a_connect_with_no_client_id_is_refused(self) -> None:
        result = handle_connect(_connect(client_id=""))
        assert isinstance(result, NukeConnectResultFailure)
        assert "client_id" in str(result.result_details)

    def test_the_first_connect_is_granted_a_session_token(self) -> None:
        result = handle_connect(_connect())
        assert isinstance(result, NukeConnectResultSuccess)
        assert result.session_token

    def test_the_same_client_id_reconnecting_is_renewed_not_refused(self) -> None:
        first = handle_connect(_connect())
        second = handle_connect(_connect())
        assert isinstance(first, NukeConnectResultSuccess)
        assert isinstance(second, NukeConnectResultSuccess)

    def test_reconnecting_mints_a_fresh_token_invalidating_the_old_one(self) -> None:
        first = handle_connect(_connect())
        second = handle_connect(_connect())
        assert isinstance(first, NukeConnectResultSuccess)
        assert isinstance(second, NukeConnectResultSuccess)
        assert first.session_token != second.session_token
        assert not session.authorize(first.session_token)
        assert session.authorize(second.session_token)

    def test_a_different_live_client_id_is_refused_and_named(self) -> None:
        handle_connect(_connect(client_id="nuke-1", client_name="Nuke 16.0v7"))

        result = handle_connect(_connect(client_id="nuke-2", client_name="Nuke 15.1v3"))

        assert isinstance(result, NukeConnectResultFailure)
        assert result.holder_client_name == "Nuke 16.0v7"
        assert "force" in str(result.result_details)

    def test_a_rejected_client_never_learns_the_holders_identity(self) -> None:
        handle_connect(_connect(client_id="nuke-1", client_name="Nuke 16.0v7"))

        result = handle_connect(_connect(client_id="nuke-2", client_name="Nuke 15.1v3"))

        assert isinstance(result, NukeConnectResultFailure)
        assert not hasattr(result, "holder_client_id")
        assert not hasattr(result, "session_token")
        assert "nuke-1" not in str(result.result_details)

    def test_force_takes_over_a_different_live_client(self) -> None:
        first = handle_connect(_connect(client_id="nuke-1", client_name="Nuke 16.0v7"))
        assert isinstance(first, NukeConnectResultSuccess)

        second = handle_connect(_connect(client_id="nuke-2", client_name="Nuke 15.1v3", force=True))

        assert isinstance(second, NukeConnectResultSuccess)
        assert not session.authorize(first.session_token)
        assert session.authorize(second.session_token)

    def test_force_against_no_holder_is_a_plain_claim(self) -> None:
        result = handle_connect(_connect(force=True))
        assert isinstance(result, NukeConnectResultSuccess)

    def test_a_stale_holder_is_displaced_without_force(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = [1000.0]
        monkeypatch.setattr(session, "_now", lambda: clock[0])
        monkeypatch.setattr(session, "engine_is_running", lambda: False)

        first = handle_connect(_connect(client_id="nuke-1", client_name="Nuke 16.0v7"))
        assert isinstance(first, NukeConnectResultSuccess)

        clock[0] += session.IDLE_WINDOW_SECONDS + 1
        second = handle_connect(_connect(client_id="nuke-2", client_name="Nuke 15.1v3"))

        assert isinstance(second, NukeConnectResultSuccess)
        assert not session.authorize(first.session_token)

    def test_a_takeover_emits_a_revocation_naming_the_revoked_id_and_new_holder(self, _fake_engine: FakeEngine) -> None:
        handle_connect(_connect(client_id="nuke-1", client_name="Nuke 16.0v7"))
        handle_connect(_connect(client_id="nuke-2", client_name="Nuke 15.1v3", force=True))

        payloads = [event.payload for event in _fake_engine.event_manager.emitted]
        revocations = [payload for payload in payloads if isinstance(payload, NukeSessionRevokedEvent)]
        assert len(revocations) == 1
        assert revocations[0].revoked_client_id == "nuke-1"
        assert revocations[0].new_holder_client_name == "Nuke 15.1v3"
        assert revocations[0].reason == "forced"

    def test_a_plain_renewal_emits_no_revocation(self, _fake_engine: FakeEngine) -> None:
        handle_connect(_connect())
        handle_connect(_connect())

        assert _fake_engine.event_manager.emitted == []
