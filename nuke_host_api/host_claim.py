"""Record which host an engine reports itself driven by."""

from __future__ import annotations

import time
from dataclasses import dataclass


def canonical_name(client_name: str) -> str:
    """Trim the name so surrounding whitespace does not make a second host."""
    return client_name.strip()


@dataclass(frozen=True)
class HostClaim:
    """``connected_at`` is epoch seconds of the holder's most recent handshake."""

    client_name: str
    connected_at: float


@dataclass(frozen=True)
class ClaimAttempt:
    """``holder`` is the claim in force after the attempt, granted or refused."""

    granted: bool
    holder: HostClaim
    displaced: str = ""


# Process-wide because a claim outlives the request that took it and no host owns the state.
_HELD: HostClaim | None = None


def held() -> HostClaim | None:
    """Return the current claim, or None when no host has connected."""
    return _HELD


def claim(client_name: str, *, force: bool = False) -> ClaimAttempt:
    """Grant a free engine, the same name reconnecting, or a forced takeover; refuse the rest."""
    global _HELD  # noqa: PLW0603

    name = canonical_name(client_name)
    current = _HELD
    same_host = current is not None and current.client_name == name

    if current is not None and not same_host and not force:
        return ClaimAttempt(granted=False, holder=current)

    displaced = "" if current is None or same_host else current.client_name
    _HELD = HostClaim(client_name=name, connected_at=time.time())
    return ClaimAttempt(granted=True, holder=_HELD, displaced=displaced)


def release() -> None:
    """Drop the claim. Nothing in the engine calls this, since a claim must outlive a reload."""
    global _HELD  # noqa: PLW0603

    _HELD = None
