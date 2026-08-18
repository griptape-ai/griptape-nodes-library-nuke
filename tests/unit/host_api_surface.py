"""Introspect the live wire surface.

Used by the frozen-snapshot test and by the regeneration script, so what gets compared and
what gets recorded can never disagree.

Only wire-visible facts are captured. Docstrings, ordering, helper names, and internal
structure are all free to change; what a plugin can observe is not.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from nuke_host_api import events, protocol
from nuke_host_api.value_types import normalize_value


def _payload_surface(payload_class: type) -> dict[str, Any]:
    """Record the fields of one payload and whether each is required.

    Required-ness matters in both directions. A field a plugin sends that becomes required
    breaks old plugins that omit it; a field a plugin reads that disappears breaks all of
    them.
    """
    fields = {}
    for field in dataclasses.fields(payload_class):
        if not field.init:
            continue
        required = field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
        fields[field.name] = {"required": required}
    return fields


def _named_constants(namespace: type) -> list[str]:
    return sorted(value for name, value in vars(namespace).items() if not name.startswith("_"))


def capture_surface() -> dict[str, Any]:
    """Return everything a host plugin can observe about this protocol version."""
    verbs = sorted(value for name, value in vars(protocol.Verb).items() if not name.startswith("_"))
    notifications = sorted(value for name, value in vars(protocol.Notification).items() if not name.startswith("_"))

    payload_names: list[str] = []
    for verb in verbs:
        stem = verb.removesuffix("Request")
        payload_names += [verb, f"{stem}ResultSuccess", f"{stem}ResultFailure"]
    payload_names += notifications

    payloads = {name: _payload_surface(getattr(events, name)) for name in payload_names if hasattr(events, name)}

    # The descriptor shape is part of the contract too: a plugin indexes these keys.
    descriptor = normalize_value("/probe/only.exr", "ImageUrlArtifact")
    descriptor_keys = sorted(descriptor)
    source_keys = sorted(descriptor["sources"][0])

    return {
        "protocol_version": protocol.PROTOCOL_VERSION,
        "supported_protocol_versions": sorted(protocol.SUPPORTED_PROTOCOL_VERSIONS),
        "verbs": verbs,
        "notifications": notifications,
        "payloads": payloads,
        "value_types": sorted(protocol.VALUE_TYPES),
        "source_kinds": sorted(protocol.SOURCE_KINDS),
        "node_states": _named_constants(protocol.NodeState),
        "execution_states": _named_constants(protocol.ExecutionState),
        "value_descriptor_keys": descriptor_keys,
        "value_source_keys": source_keys,
    }
