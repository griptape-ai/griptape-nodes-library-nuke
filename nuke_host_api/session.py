"""One Nuke client owns this engine at a time.

Nuke does not drive the engine the way the editor does. It loads a whole graph, applies
inputs, starts and cancels flows, and reads back outputs, all on the assumption that
nothing else is doing the same thing concurrently. A second connected Nuke client would
not merely see stale data, it would race the first one: two ``RunWorkflowFromRegistryRequest``
calls loading different graphs, two ``StartFlowRequest`` calls with no execution id to tell
their notifications apart (see ``protocol.ExecutionState``), a cancel that stops the wrong
run. So exactly one client may hold this engine, and every other host verb refuses to run
for anyone else.

The transport gives Python no disconnect signal (``execution_bridge`` documents the same
constraint for its own subscription), so "who currently holds the engine" cannot be learned
by watching a socket close. It is tracked here instead, as a single lease: a claimant's
identity, the token it was handed, and when it was last heard from. A claim is granted,
renewed, refused, or taken over; nothing here reaches into the transport or the engine
except the one query needed to say whether a lease may be considered stale.

Module-global and reset by ``nuke_nodes.nuke_library_advanced.NukeLibraryAdvanced`` on
unload, the same way ``execution_bridge``'s install latch and ``library_version``'s cache
are. A library reload without a process restart drops this state, so a host that held the
engine through a reload gets a session-expired refusal on its next request and must connect
again, which will succeed immediately since nobody holds a fresh lease yet.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from nuke_host_api.engine import is_running as engine_is_running

IDLE_WINDOW_SECONDS = 60.0
"""How long a held lease survives its holder going quiet, while the engine is idle.

Long enough that a host polling ``NukeGetExecutionStateRequest`` every few seconds while a
panel is open, or simply sitting between requests, is never mistaken for gone. Short enough
that a plugin that crashed or was closed without reconnecting frees its slot for another
client within about a minute rather than requiring a deliberate ``force`` takeover
indefinitely. It has no effect at all while the engine is executing: see ``_is_stale``.
"""


@dataclass
class _Lease:
    client_id: str
    client_name: str
    session_token: str
    last_seen: float


@dataclass(frozen=True)
class ClaimOutcome:
    """What a connect attempt learned, narrowed to what ``handle_connect`` needs to answer with.

    ``holder_client_name`` and ``holder_idle_seconds`` are the only facts about a live,
    still-held lease a rejected client may learn. Its ``client_id`` and ``session_token``
    never appear here: a rejected client must not be handed enough to impersonate the host
    it was refused in favour of.

    ``revoked_client_id`` and ``revocation_reason`` are set only when this claim displaced a
    *different* claimant's lease (forced or stale), never on a plain renewal by the same
    client_id, so a handler can tell the two apart without recomputing the comparison.
    """

    granted: bool
    session_token: str = ""
    refusal_reason: str = ""
    holder_client_name: str = ""
    holder_idle_seconds: float = 0.0
    revoked_client_id: str = ""
    revocation_reason: str = ""


_lease: _Lease | None = None


def _now() -> float:
    return time.monotonic()


def _mint_token() -> str:
    return secrets.token_urlsafe(32)


def _is_stale(lease: _Lease) -> bool:
    """A lease is never stale while the engine is executing.

    A host that started a long render and is waiting quietly for it to finish sends no
    requests in the meantime, and that is exactly the moment a rival must not be able to
    steal the engine out from under it. The engine query only runs once the idle window has
    already elapsed, so a live, chatty holder never pays for it.
    """
    if _now() - lease.last_seen <= IDLE_WINDOW_SECONDS:
        return False
    return not engine_is_running()


def claim(client_id: str, client_name: str, *, force: bool) -> ClaimOutcome:
    """Decide the outcome of one connect attempt and, if granted, mint a fresh token.

    A fresh token is minted on every grant, including a same-``client_id`` renewal. A
    reconnecting plugin has no earlier token to present anyway (``NukeConnectRequest``
    carries none), and handing out a new one on every successful connect means a zombie
    process from before a crash or reload cannot keep using an old token once its own
    identity has reconnected.
    """
    if not client_id:
        return ClaimOutcome(
            granted=False,
            refusal_reason=(
                "no client_id was supplied. Send a stable id, minted once per Nuke session "
                "(for example a uuid4 generated when the plugin loads) and reused across "
                "reconnects; an unnamed claimant cannot hold a lease."
            ),
        )

    global _lease  # noqa: PLW0603
    current = _lease

    if current is None or current.client_id == client_id or force or _is_stale(current):
        revoked_client_id = ""
        revocation_reason = ""
        if current is not None and current.client_id != client_id:
            revoked_client_id = current.client_id
            revocation_reason = "forced" if force else "stale"

        token = _mint_token()
        _lease = _Lease(client_id=client_id, client_name=client_name, session_token=token, last_seen=_now())
        return ClaimOutcome(
            granted=True,
            session_token=token,
            revoked_client_id=revoked_client_id,
            revocation_reason=revocation_reason,
        )

    idle_seconds = _now() - current.last_seen
    return ClaimOutcome(
        granted=False,
        refusal_reason=(
            f"host '{current.client_name}' holds this engine (last seen {idle_seconds:.0f}s ago). "
            "Retry with force=true to take over."
        ),
        holder_client_name=current.client_name,
        holder_idle_seconds=idle_seconds,
    )


def authorize(session_token: str) -> bool:
    """Check a token from any verb but connect, and refresh the lease's idleness clock on success.

    An empty, unknown, or superseded token are all refused identically: the remedy is the
    same in every case (connect again), and this module keeps no history of retired tokens
    to tell them apart. A still-current token always succeeds regardless of how long its own
    holder has been idle; idleness only matters when a *different* client_id is asking to
    take over, decided in ``claim``, never against the incumbent's own requests.
    """
    if _lease is None or not session_token or session_token != _lease.session_token:
        return False
    _lease.last_seen = _now()
    return True


def reset() -> None:
    """Drop the held lease.

    Called when the library unregisters, matching ``execution_bridge.uninstall`` and
    ``library_version.reset``. Without this a reload would keep refusing every host on the
    strength of a lease the new library instance never granted and has no way to honour.
    """
    global _lease  # noqa: PLW0603
    _lease = None
