"""Tests for the routing table.

A verb declared in protocol.py and never routed answers nothing at all, with no import
error to show for it. The engine's handler table is keyed by request type, so a missing or
duplicated entry here is silent at load and only visible when a host asks.
"""

from __future__ import annotations

from nuke_host_api import events, handlers, protocol


def test_every_verb_is_routed_to_a_handler() -> None:
    routed = {request_type.__name__ for request_type, _ in handlers.ROUTES}
    declared = {verb for name, verb in vars(protocol.Verb).items() if not name.startswith("_")}

    assert routed == declared


def test_no_request_type_is_routed_twice() -> None:
    """PayloadRegistry is keyed by name and the engine keeps one handler per type."""
    routed = [request_type for request_type, _ in handlers.ROUTES]

    assert len(routed) == len(set(routed))


def test_every_route_names_a_payload_class_this_library_owns() -> None:
    for request_type, _ in handlers.ROUTES:
        assert getattr(events, request_type.__name__, None) is request_type
