from __future__ import annotations

from collections.abc import Iterator

import pytest

from nuke_host_api import host_claim


@pytest.fixture(autouse=True)
def _released_claim() -> Iterator[None]:
    host_claim.release()
    yield
    host_claim.release()


def test_a_fresh_engine_names_no_host() -> None:
    assert host_claim.held() is None


def test_the_first_host_takes_the_claim() -> None:
    attempt = host_claim.claim("Nuke shot_040")
    assert attempt.granted
    assert attempt.holder.client_name == "Nuke shot_040"
    assert attempt.displaced == ""


def test_a_blank_name_is_still_a_claim() -> None:
    """An unnamed host must block a second one, so the empty string cannot mean "free"."""
    assert host_claim.claim("   ").holder.client_name == host_claim.UNNAMED_HOST
    assert not host_claim.claim("Nuke shot_040").granted


def test_the_same_name_reconnects() -> None:
    """A project switch and a dropped socket both force a reconnect the host did not choose."""
    host_claim.claim("Nuke shot_040")
    attempt = host_claim.claim("Nuke shot_040")
    assert attempt.granted
    assert attempt.displaced == ""


def test_surrounding_whitespace_does_not_make_a_second_host() -> None:
    host_claim.claim("Nuke shot_040")
    assert host_claim.claim("  Nuke shot_040  ").granted


def test_a_second_host_is_refused_and_told_who_holds_it() -> None:
    first = host_claim.claim("Nuke shot_040")
    attempt = host_claim.claim("Nuke shot_112")
    assert not attempt.granted
    assert attempt.holder == first.holder


def test_a_refusal_leaves_the_claim_with_the_first_host() -> None:
    host_claim.claim("Nuke shot_040")
    host_claim.claim("Nuke shot_112")
    held = host_claim.held()
    assert held is not None
    assert held.client_name == "Nuke shot_040"


def test_force_takes_the_claim_and_reports_who_lost_it() -> None:
    host_claim.claim("Nuke shot_040")
    attempt = host_claim.claim("Nuke shot_112", force=True)
    assert attempt.granted
    assert attempt.displaced == "Nuke shot_040"
    assert attempt.holder.client_name == "Nuke shot_112"


def test_forcing_a_free_engine_displaces_nobody() -> None:
    assert host_claim.claim("Nuke shot_040", force=True).displaced == ""


def test_forcing_the_same_name_is_a_reconnect_not_a_takeover() -> None:
    host_claim.claim("Nuke shot_040")
    assert host_claim.claim("Nuke shot_040", force=True).displaced == ""


def test_a_reconnect_refreshes_when_the_holder_was_last_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """The timestamp is the last handshake, which is the only host contact this layer sees."""
    times = iter([100.0, 200.0])
    monkeypatch.setattr(host_claim.time, "time", lambda: next(times))
    first = host_claim.claim("Nuke shot_040")
    second = host_claim.claim("Nuke shot_040")
    assert second.holder.connected_at > first.holder.connected_at


def test_releasing_frees_the_engine_for_any_host() -> None:
    host_claim.claim("Nuke shot_040")
    host_claim.release()
    assert host_claim.held() is None
    assert host_claim.claim("Nuke shot_112").granted
