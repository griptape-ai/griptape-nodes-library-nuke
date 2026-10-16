from __future__ import annotations

import time
from dataclasses import dataclass


def canonical_name(client_name: str) -> str:
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


# Claims survive library reloads and last until engine restart.
_HELD: HostClaim | None = None


def held() -> HostClaim | None:
    return _HELD


def claim(client_name: str, *, force: bool = False) -> ClaimAttempt:
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
    """Not called on library unload: the claim must survive reloads."""
    global _HELD  # noqa: PLW0603

    _HELD = None
