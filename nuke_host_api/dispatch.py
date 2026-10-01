"""Guard handler request types and standardize failure results."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from griptape_nodes.retained_mode.events.base_events import (
    RequestPayload,
    ResultPayload,
    ResultPayloadFailure,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def verb[R: RequestPayload](
    expected: type[R],
) -> Callable[[Callable[[R], Awaitable[ResultPayload]]], Callable[[RequestPayload], Awaitable[ResultPayload]]]:
    """Reject routing-table type mismatches before entering a handler.

    Handlers are async so the engine awaits them on its own loop. A sync handler would be
    driven on a side loop with the engine's loop blocked, starving event publication for as
    long as the handler runs.
    """

    def decorate(
        handler: Callable[[R], Awaitable[ResultPayload]],
    ) -> Callable[[RequestPayload], Awaitable[ResultPayload]]:
        @functools.wraps(handler)
        async def guarded(request: RequestPayload) -> ResultPayload:
            if not isinstance(request, expected):
                msg = f"Expected {expected.__name__}, got {type(request).__name__}"
                raise TypeError(msg)
            return await handler(request)

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
    """Use the same failure text for result details and the exception message."""
    details = f"Attempted {attempted}. Failed because {because}"
    return kind(exception=error(details), result_details=details, **fields)
