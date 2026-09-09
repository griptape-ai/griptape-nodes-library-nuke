from __future__ import annotations

import pytest
from griptape_nodes.retained_mode.events.app_events import (
    GetEngineNameRequest,
    GetEngineNameResultFailure,
    GetEngineVersionRequest,
)

from nuke_host_api import execution_bridge
from nuke_host_api.events import NukeConnectRequest, NukeConnectResultFailure, NukeConnectResultSuccess
from nuke_host_api.handlers import handle_connect
from nuke_host_api.protocol import PROTOCOL_VERSION, VALUE_TYPES
from tests.unit.host_api_fakes import ENGINE_NAME, ENGINE_VERSION, use_engine


@pytest.fixture(autouse=True)
def _fake_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    use_engine(monkeypatch, {GetEngineVersionRequest: ENGINE_VERSION, GetEngineNameRequest: ENGINE_NAME})


@pytest.fixture(autouse=True)
def _record_bridge_installs(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []
    monkeypatch.setattr(execution_bridge, "ensure_installed", lambda: calls.append(True))
    return calls


def test_connecting_installs_the_event_bridge(_record_bridge_installs: list[bool]) -> None:
    """Notifications begin at connect, so a successful connect must subscribe.

    Forgetting this is silent: every request still succeeds and no event ever arrives.
    """
    result = handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION]))
    assert isinstance(result, NukeConnectResultSuccess)
    assert _record_bridge_installs == [True]


def test_a_refused_connect_does_not_install_the_event_bridge(_record_bridge_installs: list[bool]) -> None:
    """A host that could not agree a version must not leave the engine paying for a feed."""
    result = handle_connect(NukeConnectRequest(client_protocol_versions=[99]))
    assert isinstance(result, NukeConnectResultFailure)
    assert _record_bridge_installs == []


def test_a_matching_version_connects() -> None:
    result = handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION]))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.protocol_version == PROTOCOL_VERSION
    assert result.value_types == list(VALUE_TYPES)


def test_the_event_topic_is_handed_over() -> None:
    """A host cannot derive this, so failing to return it strands notifications."""
    result = handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION]))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.event_topic == "sessions/session-abc/response"


def test_both_versions_are_reported() -> None:
    """A support ticket names an engine and a library; a host cannot look either one up."""
    result = handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION]))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.engine_version == "0.97.0"
    assert result.library_version == "0.3.0"


def test_an_empty_offer_assumes_the_current_version() -> None:
    result = handle_connect(NukeConnectRequest())
    assert isinstance(result, NukeConnectResultSuccess)


def test_an_unsupported_version_is_refused_with_the_window() -> None:
    result = handle_connect(NukeConnectRequest(client_protocol_versions=[99]))
    assert isinstance(result, NukeConnectResultFailure)
    assert result.supported_protocol_versions
    assert "99" in str(result.result_details)


def test_the_highest_mutual_version_wins() -> None:
    result = handle_connect(NukeConnectRequest(client_protocol_versions=[99, PROTOCOL_VERSION]))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.protocol_version == PROTOCOL_VERSION


def test_identity_is_read_from_the_handshake_not_the_envelope() -> None:
    result = handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION]))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.engine_id == "engine-xyz"
    assert result.session_id == "session-abc"
    assert result.engine_name == "Engine One"


def test_a_direct_engine_connection_with_no_session_reports_no_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host connecting straight to an engine, with no session layered on top, gets empty."""
    use_engine(
        monkeypatch,
        {GetEngineVersionRequest: ENGINE_VERSION, GetEngineNameRequest: ENGINE_NAME},
        session_id="",
    )
    result = handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION]))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.session_id == ""
    assert result.event_topic == "engines/engine-xyz/response"


def test_a_refused_name_lookup_reports_an_empty_name_not_a_failed_connect(monkeypatch: pytest.MonkeyPatch) -> None:
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
    result = handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION]))
    assert isinstance(result, NukeConnectResultSuccess)
    assert result.engine_name == ""
