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


def _serialize_default(field: dataclasses.Field[Any]) -> Any:
    """Render a field's default as a stable, JSON-safe value for the frozen snapshot.

    A changed default is invisible to every other check here: the field stays optional, so
    `required` does not move, but an old plugin that omits the field now gets a different
    value than the one it was built against.
    """
    if field.default is not dataclasses.MISSING:
        default = field.default
    elif field.default_factory is not dataclasses.MISSING:
        default = field.default_factory()
    else:
        return None
    if default is None or isinstance(default, (str, int, float, bool)):
        return default
    if isinstance(default, (list, tuple)):
        return list(default)
    if isinstance(default, dict):
        return dict(default)
    # No field hits this today. Falling back to repr(default) would embed a memory address
    # for an object with no custom __repr__ (an enum or dataclass default, say), making the
    # frozen-surface guard flake run to run instead of comparing a stable value. Raising
    # forces a real decision - add a case above - instead of silently shipping a flaky guard.
    msg = (
        f"{field.name!r} has a default of type {type(default).__name__}, which "
        "_serialize_default does not know how to render stably. Add a case for it."
    )
    raise TypeError(msg)


def _payload_surface(payload_class: type) -> dict[str, Any]:
    """Record each field's name, required-ness, default, and (for locally declared fields) type.

    Required-ness matters in both directions. A field a plugin sends that becomes required
    breaks old plugins that omit it; a field a plugin reads that disappears breaks all of
    them. Default is recorded too: a field that stays optional but silently changes its
    default is invisible to a required-ness check alone.

    Type is recorded, and later asserted unchanged, only for fields this package declares
    on the payload class itself. Every ``Nuke*`` payload also inherits fields
    (``request_id``, ``failure_log_level``, ``fields``, ``broadcast_result``,
    ``result_details``, ``exception``) from the engine's own ``RequestPayload`` /
    ``ResultPayload`` base classes, declared in a file this package does not control. A
    purely cosmetic restyle of an annotation there (``str | None`` becoming
    ``Optional[str]``) breaks nothing on the wire and must not trip the same guard as a
    real type change on a field this package owns.
    """
    own_fields = payload_class.__dict__.get("__annotations__", {})
    fields = {}
    for field in dataclasses.fields(payload_class):
        if not field.init:
            continue
        required = field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
        entry: dict[str, Any] = {
            "required": required,
            "default": None if required else _serialize_default(field),
        }
        if field.name in own_fields:
            entry["type"] = str(field.type)
        fields[field.name] = entry
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
