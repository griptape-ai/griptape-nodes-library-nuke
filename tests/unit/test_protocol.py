"""Tests for the frozen surface.

These are the tests most worth having. Everything else can be fixed in a release; a name
in ``protocol.py`` that drifts from the class it points at breaks a compiled plugin that
cannot be fixed for a year.
"""

from __future__ import annotations

import inspect

import pytest

from nuke_host_api import events, protocol


def test_verb_names_match_real_payload_classes() -> None:
    """Every verb string must name a class that actually exists.

    ``protocol.Verb`` holds strings because a host names types on the wire rather than
    importing them. That decoupling is exactly what lets a rename pass code review while
    silently breaking every plugin, so it is asserted here.
    """
    for attribute, verb in vars(protocol.Verb).items():
        if attribute.startswith("_"):
            continue
        assert hasattr(events, verb), f"Verb.{attribute} names '{verb}', which does not exist in events.py"


def test_notification_names_match_real_payload_classes() -> None:
    """Same guarantee for pushed events."""
    for attribute, notification in vars(protocol.Notification).items():
        if attribute.startswith("_"):
            continue
        assert hasattr(events, notification), (
            f"Notification.{attribute} names '{notification}', which does not exist in events.py"
        )


def test_every_verb_has_a_success_and_failure_result() -> None:
    """A host must always get a typed answer, never a bare exception."""
    for attribute, verb in vars(protocol.Verb).items():
        if attribute.startswith("_"):
            continue
        stem = verb.removesuffix("Request")
        assert hasattr(events, f"{stem}ResultSuccess"), f"{verb} has no success result"
        assert hasattr(events, f"{stem}ResultFailure"), f"{verb} has no failure result"


def test_registered_payload_classes_all_carry_the_nuke_prefix() -> None:
    """PayloadRegistry is keyed by bare class name and silently overwrites collisions.

    So every payload this library registers must be prefixed, or it can quietly displace
    another library's or the engine's type of the same name.
    """
    from griptape_nodes.retained_mode.events.base_events import Payload

    unprefixed = [
        name
        for name, member in vars(events).items()
        if inspect.isclass(member) and issubclass(member, Payload) and member.__module__ == events.__name__
        if not name.startswith("Nuke")
    ]
    assert not unprefixed, f"Unprefixed payload classes risk a registry collision: {unprefixed}"


def test_value_type_set_is_closed_and_consistent() -> None:
    """VALUE_TYPES must list exactly the ValueType members, no more and no fewer."""
    declared = {value for name, value in vars(protocol.ValueType).items() if not name.startswith("_")}
    assert set(protocol.VALUE_TYPES) == declared
    assert len(protocol.VALUE_TYPES) == len(declared), "VALUE_TYPES contains duplicates"


def test_value_type_wire_strings_are_exactly_these() -> None:
    """The literal strings, not the attribute names, are what a compiled plugin switches on.

    Every other test here refers to these symbolically, so renaming a wire string while
    keeping its attribute would pass all of them and silently break every shipped plugin.
    Spelled out literally so that rename cannot happen quietly.
    """
    assert protocol.ValueType.IMAGE == "GTImage"
    assert protocol.ValueType.MOVIE == "GTMovie"
    assert protocol.ValueType.FILE == "GTFile"
    assert protocol.ValueType.TEXT == "GTText"
    assert protocol.ValueType.NUMBER == "GTNumber"
    assert protocol.ValueType.BOOL == "GTBool"
    assert protocol.ValueType.NULL == "GTNull"


def test_source_kind_wire_strings_are_exactly_these() -> None:
    assert protocol.SourceKind.URL == "url"
    assert protocol.SourceKind.PATH == "path"
    assert protocol.SourceKind.INLINE == "inline"
    assert protocol.SourceKind.MACRO == "macro"


def test_source_kind_set_is_closed_and_consistent() -> None:
    declared = {value for name, value in vars(protocol.SourceKind).items() if not name.startswith("_")}
    assert set(protocol.SOURCE_KINDS) == declared


def test_parameter_section_wire_strings_are_exactly_these() -> None:
    """Also the strings ``NukeDescribeWorkflowResultSuccess`` already uses for its two fields."""
    assert protocol.ParameterSection.INPUTS == "inputs"
    assert protocol.ParameterSection.OUTPUTS == "outputs"


def test_parameter_section_set_is_closed_and_consistent() -> None:
    declared = {value for name, value in vars(protocol.ParameterSection).items() if not name.startswith("_")}
    assert set(protocol.PARAMETER_SECTIONS) == declared


def test_current_protocol_version_is_inside_the_support_window() -> None:
    """Shipping a version the library will not accept would refuse every host."""
    assert protocol.PROTOCOL_VERSION in protocol.SUPPORTED_PROTOCOL_VERSIONS


@pytest.mark.parametrize("namespace", [protocol.NodeState, protocol.ExecutionState])
def test_state_values_are_lowercase_and_unique(namespace: type) -> None:
    """States travel on the wire, so casing is part of the contract."""
    values = [value for name, value in vars(namespace).items() if not name.startswith("_")]
    assert values == [value.lower() for value in values]
    assert len(values) == len(set(values))
