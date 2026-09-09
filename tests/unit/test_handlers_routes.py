"""Guards the routing table against omissions and duplicates."""

from __future__ import annotations

import inspect

from nuke_host_api import events, handlers, protocol


def test_every_verb_is_routed_to_a_handler() -> None:
    routed = {request_type.__name__ for request_type, _ in handlers.ROUTES}
    declared = {verb for name, verb in vars(protocol.Verb).items() if not name.startswith("_")}

    assert routed == declared


def test_no_request_type_is_routed_twice() -> None:
    routed = [request_type for request_type, _ in handlers.ROUTES]

    assert len(routed) == len(set(routed))


def test_every_route_names_a_payload_class_this_library_owns() -> None:
    for request_type, _ in handlers.ROUTES:
        assert getattr(events, request_type.__name__, None) is request_type


def test_every_handler_is_a_coroutine_function() -> None:
    """The engine drives a sync handler on a side loop with its own loop blocked, which stops
    event publication for as long as the handler runs. A run holds one for its whole length.
    """
    sync_handlers = [
        request_type.__name__ for request_type, handler in handlers.ROUTES if not inspect.iscoroutinefunction(handler)
    ]

    assert not sync_handlers
