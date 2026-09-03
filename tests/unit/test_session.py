"""Tests for the exclusive engine lease.

Time is injected throughout rather than slept, since the idle window matters here and a
real sleep would make this suite the slowest thing in it for no benefit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nuke_host_api import session

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _authorized_session() -> None:
    """This file tests the real gate; the shared bypass in conftest.py must not apply here.

    Redefining the fixture under the same name shadows the conftest.py one for every test in
    this module.
    """
    return


@pytest.fixture(autouse=True)
def _reset_lease() -> Iterator[None]:
    """One process-global lease; a leftover claim from another test must not leak in."""
    session.reset()
    yield
    session.reset()


class _Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(session, "_now", fake)
    return fake


@pytest.fixture
def engine_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session, "engine_is_running", lambda: False)


@pytest.fixture
def engine_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session, "engine_is_running", lambda: True)


class TestClaim:
    def test_an_empty_client_id_is_refused(self, engine_idle: None) -> None:  # noqa: ARG002
        outcome = session.claim("", "Nuke 16.0v7", force=False)
        assert not outcome.granted
        assert "client_id" in outcome.refusal_reason

    def test_no_holder_grants_unconditionally(self, engine_idle: None) -> None:  # noqa: ARG002
        outcome = session.claim("nuke-1", "Nuke 16.0v7", force=False)
        assert outcome.granted
        assert outcome.session_token
        assert not outcome.revoked_client_id

    def test_the_same_client_id_reconnecting_renews_with_a_fresh_token(self, engine_idle: None) -> None:  # noqa: ARG002
        first = session.claim("nuke-1", "Nuke 16.0v7", force=False)
        second = session.claim("nuke-1", "Nuke 16.0v7", force=False)

        assert second.granted
        assert second.session_token != first.session_token
        assert not second.revoked_client_id, "a renewal is not a takeover of a different party"

    def test_a_renewal_invalidates_the_lease_holders_own_earlier_token(self, engine_idle: None) -> None:  # noqa: ARG002
        first = session.claim("nuke-1", "Nuke 16.0v7", force=False)
        session.claim("nuke-1", "Nuke 16.0v7", force=False)

        assert not session.authorize(first.session_token)

    def test_a_different_client_id_is_refused_while_the_holder_is_live(self, engine_idle: None) -> None:  # noqa: ARG002
        session.claim("nuke-1", "Nuke 16.0v7", force=False)

        outcome = session.claim("nuke-2", "Nuke 15.1v3", force=False)

        assert not outcome.granted
        assert "force" in outcome.refusal_reason

    def test_the_refusal_names_the_holder_but_never_its_identity(self, engine_idle: None) -> None:  # noqa: ARG002
        session.claim("nuke-1", "Nuke 16.0v7", force=False)

        outcome = session.claim("nuke-2", "Nuke 15.1v3", force=False)

        assert outcome.holder_client_name == "Nuke 16.0v7"
        assert not hasattr(outcome, "holder_client_id")
        assert not hasattr(outcome, "session_token") or outcome.session_token == ""

    def test_the_refusal_reports_how_long_the_holder_has_been_idle(self, clock: _Clock, engine_idle: None) -> None:  # noqa: ARG002
        session.claim("nuke-1", "Nuke 16.0v7", force=False)
        clock.advance(12.0)

        outcome = session.claim("nuke-2", "Nuke 15.1v3", force=False)

        assert outcome.holder_idle_seconds == pytest.approx(12.0)

    def test_force_takes_over_a_live_holder(self, engine_idle: None) -> None:  # noqa: ARG002
        first = session.claim("nuke-1", "Nuke 16.0v7", force=False)

        second = session.claim("nuke-2", "Nuke 15.1v3", force=True)

        assert second.granted
        assert second.revoked_client_id == "nuke-1"
        assert second.revocation_reason == "forced"
        assert not session.authorize(first.session_token)
        assert session.authorize(second.session_token)

    def test_force_against_no_holder_grants_with_no_revocation(self, engine_idle: None) -> None:  # noqa: ARG002
        outcome = session.claim("nuke-1", "Nuke 16.0v7", force=True)

        assert outcome.granted
        assert not outcome.revoked_client_id

    def test_a_lease_survives_up_to_the_idle_window(self, clock: _Clock, engine_idle: None) -> None:  # noqa: ARG002
        session.claim("nuke-1", "Nuke 16.0v7", force=False)
        clock.advance(session.IDLE_WINDOW_SECONDS)

        outcome = session.claim("nuke-2", "Nuke 15.1v3", force=False)

        assert not outcome.granted, "the idle window has not yet elapsed"

    def test_a_different_client_id_claims_once_the_holder_goes_stale(self, clock: _Clock, engine_idle: None) -> None:  # noqa: ARG002
        first = session.claim("nuke-1", "Nuke 16.0v7", force=False)
        clock.advance(session.IDLE_WINDOW_SECONDS + 1)

        second = session.claim("nuke-2", "Nuke 15.1v3", force=False)

        assert second.granted
        assert second.revoked_client_id == "nuke-1"
        assert second.revocation_reason == "stale"
        assert not session.authorize(first.session_token)

    def test_a_lease_never_goes_stale_while_the_engine_is_running(
        self,
        clock: _Clock,
        engine_running: None,  # noqa: ARG002
    ) -> None:
        """A host waiting quietly through a long render must not be stolen from."""
        session.claim("nuke-1", "Nuke 16.0v7", force=False)
        clock.advance(session.IDLE_WINDOW_SECONDS * 10)

        outcome = session.claim("nuke-2", "Nuke 15.1v3", force=False)

        assert not outcome.granted


class TestAuthorize:
    def test_the_current_token_is_authorized(self, engine_idle: None) -> None:  # noqa: ARG002
        outcome = session.claim("nuke-1", "Nuke 16.0v7", force=False)
        assert session.authorize(outcome.session_token)

    def test_an_empty_token_is_never_authorized(self, engine_idle: None) -> None:  # noqa: ARG002
        session.claim("nuke-1", "Nuke 16.0v7", force=False)
        assert not session.authorize("")

    def test_an_unknown_token_is_refused(self, engine_idle: None) -> None:  # noqa: ARG002
        session.claim("nuke-1", "Nuke 16.0v7", force=False)
        assert not session.authorize("not-a-real-token")

    def test_a_token_is_refused_with_no_lease_at_all(self) -> None:
        assert not session.authorize("anything")

    def test_a_superseded_token_is_refused_after_a_takeover(self, engine_idle: None) -> None:  # noqa: ARG002
        first = session.claim("nuke-1", "Nuke 16.0v7", force=False)
        session.claim("nuke-2", "Nuke 15.1v3", force=True)

        assert not session.authorize(first.session_token)

    def test_authorizing_refreshes_the_lease_so_the_holder_is_never_locked_out_by_its_own_idleness(
        self,
        clock: _Clock,
        engine_idle: None,  # noqa: ARG002
    ) -> None:
        outcome = session.claim("nuke-1", "Nuke 16.0v7", force=False)
        clock.advance(session.IDLE_WINDOW_SECONDS * 10)

        assert session.authorize(outcome.session_token), "idleness only matters to a rival's claim, not its own use"

    def test_authorizing_the_holders_own_token_after_a_long_idle_still_blocks_a_rival(
        self,
        clock: _Clock,
        engine_idle: None,  # noqa: ARG002
    ) -> None:
        outcome = session.claim("nuke-1", "Nuke 16.0v7", force=False)
        clock.advance(session.IDLE_WINDOW_SECONDS + 1)
        session.authorize(outcome.session_token)

        rival = session.claim("nuke-2", "Nuke 15.1v3", force=False)

        assert not rival.granted, "a request just refreshed last_seen, so the lease is fresh again"


class TestReset:
    def test_reset_drops_the_lease_so_the_next_claim_is_unconditional(self, engine_idle: None) -> None:  # noqa: ARG002
        outcome = session.claim("nuke-1", "Nuke 16.0v7", force=False)

        session.reset()

        assert not session.authorize(outcome.session_token)
        after_reset = session.claim("nuke-2", "Nuke 15.1v3", force=False)
        assert after_reset.granted
        assert not after_reset.revoked_client_id
