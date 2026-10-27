from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from griptape_nodes.retained_mode.events.app_events import (
    AppStartSessionRequest,
    AppStartSessionResultFailure,
    GetEngineNameRequest,
    GetEngineNameResultFailure,
    GetEngineVersionRequest,
)

from nuke_host_api import execution_bridge, host_claim, notify
from nuke_host_api.events import (
    NukeConnectRequest,
    NukeConnectResultFailure,
    NukeConnectResultSuccess,
    NukeDisconnectRequest,
    NukeDisconnectResultFailure,
    NukeDisconnectResultSuccess,
)
from nuke_host_api.handlers import handle_connect, handle_disconnect
from nuke_host_api.protocol import PROTOCOL_VERSION, VALUE_TYPES, DisconnectCause
from tests.unit.host_api_fakes import ENGINE_NAME, ENGINE_VERSION, FakeEngine, use_engine

HOST = "Nuke shot_040"


@pytest.fixture(autouse=True)
def _released_claim() -> Iterator[None]:
    host_claim.release()
    yield
    host_claim.release()


@pytest.fixture(autouse=True)
def _published(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    published: list[Any] = []
    monkeypatch.setattr(notify, "publish", published.append)
    return published


@pytest.fixture(autouse=True)
def _fake_engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    return use_engine(monkeypatch, {GetEngineVersionRequest: ENGINE_VERSION, GetEngineNameRequest: ENGINE_NAME})


@pytest.fixture(autouse=True)
def _record_bridge_installs(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []
    monkeypatch.setattr(execution_bridge, "ensure_installed", lambda: calls.append(True))
    return calls


async def test_connecting_installs_the_event_bridge(_record_bridge_installs: list[bool]) -> None:
    """Notifications begin at connect, so a successful connect must subscribe.

    Forgetting this is silent: every request still succeeds and no event ever arrives.
    """
    result = await handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION], client_name=HOST))
    assert isinstance(result, NukeConnectResultSuccess)
    assert _record_bridge_installs == [True]


async def test_a_refused_connect_does_not_install_the_event_bridge(_record_bridge_installs: list[bool]) -> None:
    """A host that could not agree a version must not leave the engine paying for a feed."""
    result = await handle_connect(NukeConnectRequest(client_protocol_versions=[99], client_name=HOST))
    assert isinstance(result, NukeConnectResultFailure)
    assert _record_bridge_installs == []


@pytest.mark.parametrize("client_name", ["", "   "])
async def test_a_host_with_no_name_is_refused_and_takes_no_claim(client_name: str) -> None:
    """A name is required to distinguish hosts for claim refusals and takeovers."""
    result = await handle_connect(
        NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION], client_name=client_name)
    )
    assert isinstance(result, NukeConnectResultFailure)
    assert "client_name" in str(result.result_details)
    assert host_claim.held() is None


async def test_a_matching_version_connects() -> None:
    result = await handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION], client_name=HOST))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.protocol_version == PROTOCOL_VERSION
    assert result.value_types == list(VALUE_TYPES)


async def test_the_event_topic_is_handed_over() -> None:
    """A host cannot derive this, so failing to return it strands notifications."""
    result = await handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION], client_name=HOST))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.event_topic == "sessions/session-abc/response"


async def test_both_versions_are_reported() -> None:
    """A support ticket names an engine and a library; a host cannot look either one up."""
    result = await handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION], client_name=HOST))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.engine_version == "0.97.0"
    assert result.library_version == "0.3.0"


async def test_an_empty_offer_assumes_the_current_version() -> None:
    result = await handle_connect(NukeConnectRequest(client_name=HOST))
    assert isinstance(result, NukeConnectResultSuccess)


async def test_an_unsupported_version_is_refused_with_the_window() -> None:
    result = await handle_connect(NukeConnectRequest(client_protocol_versions=[99], client_name=HOST))
    assert isinstance(result, NukeConnectResultFailure)
    assert result.supported_protocol_versions
    assert "99" in str(result.result_details)


async def test_the_highest_mutual_version_wins() -> None:
    result = await handle_connect(NukeConnectRequest(client_protocol_versions=[99, PROTOCOL_VERSION], client_name=HOST))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.protocol_version == PROTOCOL_VERSION


async def test_identity_is_read_from_the_handshake_not_the_envelope() -> None:
    result = await handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION], client_name=HOST))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.engine_id == "engine-xyz"
    assert result.session_id == "session-abc"
    assert result.engine_name == "Engine One"


async def test_a_direct_engine_connection_with_no_session_opens_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery lists clients per session, so a host on a sessionless engine opens one to be seen."""
    use_engine(
        monkeypatch,
        {GetEngineVersionRequest: ENGINE_VERSION, GetEngineNameRequest: ENGINE_NAME},
        session_id="",
    )
    result = await handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION], client_name=HOST))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.session_id == "session-opened"
    assert result.event_topic == "sessions/session-opened/response"


async def test_a_connect_joins_the_session_under_its_claim_name(_fake_engine: FakeEngine) -> None:
    """Engine discovery shows who holds an engine, so the start request must carry the trimmed name."""
    await handle_connect(NukeConnectRequest(client_name="  Nuke shot_040 "))

    starts = [r for r in _fake_engine.requests if isinstance(r, AppStartSessionRequest)]
    assert [(r.client_id, r.client_type) for r in starts] == [("Nuke shot_040", "nuke")]
    assert _fake_engine.session_clients == [("Nuke shot_040", "nuke")]


async def test_a_takeover_delists_the_displaced_host(_fake_engine: FakeEngine) -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_112", force=True))

    assert _fake_engine.session_clients == [("Nuke shot_112", "nuke")]


async def test_a_refused_connect_lists_nobody(_fake_engine: FakeEngine) -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_112"))

    assert _fake_engine.session_clients == [("Nuke shot_040", "nuke")]


async def test_the_same_host_reconnecting_is_listed_once(_fake_engine: FakeEngine) -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))

    assert _fake_engine.session_clients == [("Nuke shot_040", "nuke")]


async def test_a_session_that_will_not_start_still_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Being listed in discovery is a courtesy; driving the engine never depended on a session."""
    fake = use_engine(
        monkeypatch,
        {
            GetEngineVersionRequest: ENGINE_VERSION,
            GetEngineNameRequest: ENGINE_NAME,
            AppStartSessionRequest: AppStartSessionResultFailure(result_details="no sessions here"),
        },
        session_id="",
    )
    result = await handle_connect(NukeConnectRequest(client_name=HOST))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.session_id == ""
    assert fake.session_clients == []


async def test_a_refused_name_lookup_reports_an_empty_name_not_a_failed_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine's own name lookup fails only on an unexpected exception, never on an unset
    name. Either way, connect is still a successful handshake.
    """
    use_engine(
        monkeypatch,
        {
            GetEngineVersionRequest: ENGINE_VERSION,
            GetEngineNameRequest: GetEngineNameResultFailure(error_message="boom", result_details="boom"),
        },
    )
    result = await handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION], client_name=HOST))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.engine_name == ""


async def test_a_connect_reports_the_host_it_claimed_the_engine_for() -> None:
    result = await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.host_client_name == "Nuke shot_040"
    assert result.host_connected_at > 0
    assert result.displaced_client_name == ""


async def test_a_second_host_is_refused_and_told_who_has_the_engine() -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    result = await handle_connect(NukeConnectRequest(client_name="Nuke shot_112"))
    assert isinstance(result, NukeConnectResultFailure)
    assert result.host_client_name == "Nuke shot_040"
    assert result.host_connected_at > 0
    assert "force=true" in str(result.result_details)


async def test_a_refused_second_host_still_learns_the_support_window() -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    result = await handle_connect(NukeConnectRequest(client_name="Nuke shot_112"))
    assert isinstance(result, NukeConnectResultFailure)
    assert result.supported_protocol_versions


async def test_a_version_refusal_names_no_host() -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    result = await handle_connect(NukeConnectRequest(client_protocol_versions=[99], client_name="Nuke shot_112"))
    assert isinstance(result, NukeConnectResultFailure)
    assert result.host_client_name == ""


async def test_an_unsupported_version_does_not_take_the_claim() -> None:
    await handle_connect(NukeConnectRequest(client_protocol_versions=[99], client_name="Nuke shot_112"))
    assert host_claim.held() is None


async def test_the_same_host_reconnects_without_forcing() -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    result = await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.displaced_client_name == ""


async def test_force_takes_over_and_names_the_host_it_displaced() -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    result = await handle_connect(NukeConnectRequest(client_name="Nuke shot_112", force=True))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.host_client_name == "Nuke shot_112"
    assert result.displaced_client_name == "Nuke shot_040"


async def test_a_refused_second_host_does_not_install_the_event_bridge(
    _record_bridge_installs: list[bool],
) -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_112"))
    assert _record_bridge_installs == [True]


async def test_a_clean_disconnect_delists_the_host(_fake_engine: FakeEngine) -> None:
    """Discovery shows the claim holder, so releasing the claim must also leave the session."""
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    assert _fake_engine.session_clients == [("Nuke shot_040", "nuke")]

    await handle_disconnect(NukeDisconnectRequest(client_name="Nuke shot_040"))

    assert _fake_engine.session_clients == []


async def test_a_disconnect_from_a_non_holder_delists_nobody(_fake_engine: FakeEngine) -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))

    await handle_disconnect(NukeDisconnectRequest(client_name="Nuke shot_112"))

    assert _fake_engine.session_clients == [("Nuke shot_040", "nuke")]


async def test_a_takeover_asks_the_displaced_host_to_disconnect(_published: list[Any]) -> None:
    """The transport cannot close another host's socket, so the host must close its own."""
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_112", force=True))

    assert len(_published) == 1
    event = _published[0]
    assert event.client_name == "Nuke shot_040"
    assert event.replaced_by == "Nuke shot_112"
    assert event.cause == DisconnectCause.CLAIM_TAKEN
    assert "Nuke shot_112" in event.reason


async def test_nothing_is_asked_to_disconnect_when_no_host_was_displaced(_published: list[Any]) -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040", force=True))
    assert _published == []


async def test_a_refused_connect_asks_nobody_to_disconnect(_published: list[Any]) -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_112"))
    assert _published == []


async def test_disconnecting_lets_another_host_connect_without_force() -> None:
    """Closing Nuke and reopening it under a new script name must not need a takeover."""
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))

    result = await handle_disconnect(NukeDisconnectRequest(client_name="Nuke shot_040"))
    assert isinstance(result, NukeDisconnectResultSuccess)
    assert result.released
    assert result.host_client_name == ""

    reconnect = await handle_connect(NukeConnectRequest(client_name="Nuke shot_112"))
    assert isinstance(reconnect, NukeConnectResultSuccess)
    assert reconnect.displaced_client_name == ""


async def test_a_displaced_host_disconnecting_leaves_the_new_host_in_place() -> None:
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_112", force=True))

    result = await handle_disconnect(NukeDisconnectRequest(client_name="Nuke shot_040"))
    assert isinstance(result, NukeDisconnectResultSuccess)
    assert not result.released
    assert result.host_client_name == "Nuke shot_112"
    held = host_claim.held()
    assert held is not None
    assert held.client_name == "Nuke shot_112"


async def test_disconnecting_twice_succeeds_without_releasing_again() -> None:
    """A host may send it on both script close and app exit."""
    await handle_connect(NukeConnectRequest(client_name="Nuke shot_040"))
    await handle_disconnect(NukeDisconnectRequest(client_name="Nuke shot_040"))

    result = await handle_disconnect(NukeDisconnectRequest(client_name="Nuke shot_040"))
    assert isinstance(result, NukeDisconnectResultSuccess)
    assert not result.released


@pytest.mark.parametrize("client_name", ["", "   "])
async def test_a_disconnect_with_no_name_is_refused_and_keeps_the_claim(client_name: str) -> None:
    await handle_connect(NukeConnectRequest(client_name=HOST))

    result = await handle_disconnect(NukeDisconnectRequest(client_name=client_name))
    assert isinstance(result, NukeDisconnectResultFailure)
    assert "client_name" in str(result.result_details)
    assert host_claim.held() is not None
