"""The handler calling convention: narrow the request in, word the failure out.

Both halves are boilerplate every verb would otherwise repeat, and the wording is part of
what a host sees, so it is built in one place rather than retyped six times.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from griptape_nodes.retained_mode.events.base_events import (
    RequestPayload,
    ResultPayload,
    ResultPayloadFailure,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def verb[R: RequestPayload](
    expected: type[R],
) -> Callable[[Callable[[R], ResultPayload]], Callable[[RequestPayload], ResultPayload]]:
    """Bind a handler to the one request type it accepts.

    The engine's handler table is typed as ``RequestPayload`` in and ``ResultPayload`` out,
    so without this each handler starts by re-narrowing its own argument and a mix-up in the
    registry would otherwise reach the body as a wrong-typed payload. Guarding here lets the
    body declare the type it actually wants and be checked against it.
    """

    def decorate(handler: Callable[[R], ResultPayload]) -> Callable[[RequestPayload], ResultPayload]:
        @functools.wraps(handler)
        def guarded(request: RequestPayload) -> ResultPayload:
            if not isinstance(request, expected):
                msg = f"Expected {expected.__name__}, got {type(request).__name__}"
                raise TypeError(msg)
            return handler(request)

        return guarded

    return decorate


def failure[F: ResultPayloadFailure](
    kind: type[F],
    *,
    attempted: str,
    because: str,
    error: type[Exception] = RuntimeError,
    **fields: Any,
) -> F:
    """Build a failure result in the one shape a host is promised.

    "Attempted X. Failed because Y." is the whole contract: what was tried, why it did not
    happen, and where remediation belongs when there is any. ``because`` carries its own
    terminal punctuation and any following sentence, so a handler can append the engine's
    own words or tell a host what to do next.

    The same text becomes both ``result_details`` and the exception's message, since a host
    reading either one should never see two different accounts of the same refusal.
    """
    details = f"Attempted {attempted}. Failed because {because}"
    return kind(exception=error(details), result_details=details, **fields)
