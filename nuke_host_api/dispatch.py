"""Guard handler request types and standardize failure results."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from griptape_nodes.retained_mode.events.base_events import (
    RequestPayload,
    ResultPayload,
    ResultPayloadFailure,
)

from nuke_host_api import loaded_workflow

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def verb[R: RequestPayload](
    expected: type[R],
    *,
    bind_loaded_workflow: bool = True,
) -> Callable[[Callable[[R], Awaitable[ResultPayload]]], Callable[[RequestPayload], Awaitable[ResultPayload]]]:
    """Reject routing-table type mismatches before entering a handler.

    Handlers are async so the engine awaits them on its own loop. A sync handler would be
    driven on a side loop with the engine's loop blocked, starving event publication for as
    long as the handler runs.

    Handlers run bound to the host's loaded workflow so their engine requests name it. Load opts
    out because it closes that workflow partway through.
    """

    def decorate(
        handler: Callable[[R], Awaitable[ResultPayload]],
    ) -> Callable[[RequestPayload], Awaitable[ResultPayload]]:
        @functools.wraps(handler)
        async def guarded(request: RequestPayload) -> ResultPayload:
            if not isinstance(request, expected):
                msg = f"Expected {expected.__name__}, got {type(request).__name__}"
                raise TypeError(msg)
            if not bind_loaded_workflow:
                return await handler(request)
            with loaded_workflow.bound():
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
