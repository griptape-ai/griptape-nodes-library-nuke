"""Tests for version negotiation and opening the event stream."""

from __future__ import annotations

import pytest
from griptape_nodes.retained_mode.events.app_events import GetEngineVersionRequest

from nuke_host_api import execution_bridge
from nuke_host_api.events import NukeConnectRequest, NukeConnectResultFailure, NukeConnectResultSuccess
from nuke_host_api.handlers import handle_connect
from nuke_host_api.protocol import PROTOCOL_VERSION, VALUE_TYPES
from tests.unit.host_api_fakes import ENGINE_VERSION, use_engine


@pytest.fixture(autouse=True)
def _fake_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    use_engine(monkeypatch, {GetEngineVersionRequest: ENGINE_VERSION})


@pytest.fixture(autouse=True)
def _record_bridge_installs(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Stub the real install, which would subscribe this process to the engine's feed."""
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
    """Keeps a bare connectivity check working."""
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
