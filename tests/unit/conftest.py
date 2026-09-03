"""Shared fixtures for the host API unit tests."""

from __future__ import annotations

import pytest

from nuke_host_api import session


@pytest.fixture(autouse=True)
def _authorized_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass the session gate for tests about something other than sessions.

    Nearly every handler test exercises workflow or execution logic and has no reason to
    also thread a valid session_token through every request it builds. The gate itself is
    exercised for real in test_dispatch.py, test_handlers_connect.py, and test_session.py,
    each of which redefines this fixture as a no-op so the real check runs.

    ``session.reset()`` runs first regardless, since ``session`` holds one process-global
    lease and a test that forgets to clean up after itself would otherwise leak a claim into
    whichever test happens to run next.
    """
    session.reset()
    monkeypatch.setattr(session, "authorize", lambda _token: True)
