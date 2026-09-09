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
    from collections.abc import Callable


def verb[R: RequestPayload](
    expected: type[R],
) -> Callable[[Callable[[R], ResultPayload]], Callable[[RequestPayload], ResultPayload]]:
    """Reject routing-table type mismatches before entering a handler."""

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
    """Use the same failure text for result details and the exception message."""
    details = f"Attempted {attempted}. Failed because {because}"
    return kind(exception=error(details), result_details=details, **fields)
