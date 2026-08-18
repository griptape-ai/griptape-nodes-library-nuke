"""Host-facing data types and the value normalizer.

The engine expresses "an image" in at least six shapes: an ``ImageArtifact`` with
inline bytes, an ``ImageUrlArtifact`` wrapping a static-server URL, a bare string
holding that same URL, a workspace-relative path string, an absolute path string,
or a ``ListArtifact`` of any of those. ``BlobArtifact``, ``VideoUrlArtifact``, and
``GenericArtifact`` are structurally identical to ``ImageUrlArtifact`` (all carry a
single ``value``), so the class name is the only discriminator.

This module collapses all of that into a small closed set of host types with one
structured descriptor shape.

Deliberate non-goals: this normalizer moves no bytes. It does not download, copy,
sniff file headers, or write anything. The engine writes wherever it writes; this
layer only makes the *shape* of the value predictable. A format is reported only
when it is actually known, never guessed, so a host is never told a JPEG is a PNG.

It does perform *pure resolution*: project directory macros like ``{outputs}/render.png``
are resolved through ``GetPathForMacroRequest``, which is a pure resolver with no disk
writes (``project_manager.on_get_path_for_macro_request``). A host always needs a real
path, and resolving one is a lookup, not I/O.

Versioning property this buys: mapping a newly invented engine artifact class into
an existing host type is an additive change and does not bump the protocol version.
Adding a host type changes what the host must switch on, and does bump it.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from griptape_nodes.common.macro_parser import ParsedMacro
from griptape_nodes.common.macro_parser.exceptions import MacroSyntaxError
from griptape_nodes.retained_mode.events.project_events import (
    GetPathForMacroRequest,
    GetPathForMacroResultSuccess,
    UnresolvedSequenceSlotBehavior,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.protocol import SourceKind, ValueType

logger = logging.getLogger("griptape_nodes")

IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "exr", "tif", "tiff", "webp", "dpx", "tga", "hdr"})
VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "avi", "mkv", "webm", "m4v"})

# Any brace token at all. Both project directory macros ({outputs}) and workflow
# variables ({MY_VAR}) use this shape, so presence of braces alone proves nothing
# about which system a token belongs to.
_HAS_BRACE_TOKEN = re.compile(r"\{[^{}]*\}")

# Runs of hash glyphs, the frame-number convention Nuke reads natively.
_HASH_RUN = re.compile(r"#+")

# Engine parameter type names mapped to host types. Unrecognized names fall back to
# GTFile when they look artifact-shaped and GTText otherwise, so a host never sees a
# type it has no case for.
ENGINE_TYPE_TO_VALUE_TYPE = {
    "ImageArtifact": ValueType.IMAGE,
    "ImageUrlArtifact": ValueType.IMAGE,
    "VideoUrlArtifact": ValueType.VIDEO,
    "str": ValueType.TEXT,
    "string": ValueType.TEXT,
    "int": ValueType.NUMBER,
    "float": ValueType.NUMBER,
    "bool": ValueType.BOOLEAN,
}


def value_type_for_engine_type(engine_type: str | None) -> str:
    """Map a declared engine parameter type name to a value type.

    Used for port metadata in describe_workflow, where only the type *name* is
    available and no value has been produced yet.
    """
    if engine_type is None:
        return ValueType.TEXT
    mapped = ENGINE_TYPE_TO_VALUE_TYPE.get(engine_type)
    if mapped is not None:
        return mapped
    if engine_type.endswith("Artifact"):
        return ValueType.FILE
    return ValueType.TEXT


def _extension_of(locator: str) -> str | None:
    """Return the lowercase extension of a URL or path, or None when absent."""
    path_part = locator
    if locator.startswith(("http://", "https://")):
        path_part = urlparse(locator).path
    if "." not in path_part.rsplit("/", 1)[-1]:
        return None
    extension = path_part.rsplit(".", 1)[-1].lower()
    if not extension or not extension.isalnum():
        return None
    return extension


def _value_type_for_extension(extension: str | None) -> str:
    """Classify a file by extension. Unknown extensions are GTFile, not a guess."""
    if extension in IMAGE_EXTENSIONS:
        return ValueType.IMAGE
    if extension in VIDEO_EXTENSIONS:
        return ValueType.VIDEO
    return ValueType.FILE


def _resolve_macro(locator: str) -> dict[str, Any] | None:
    """Resolve a macro template to a path, or return None when it is not a macro.

    Sequence slots are rendered as hash glyphs (``render.####.exr``) rather than
    failing. That is the engine's ``RENDER_SEQUENCE_PATTERN`` mode, documented as
    presentation-only because the result is not openable. A Nuke Read node is the
    one consumer for which the pattern form is the *operationally correct* form,
    since Nuke expands the padding itself. The returned source therefore sets
    ``is_pattern`` so a host knows it may hand the string to a Read node but must
    not open it directly.

    Returns None when the string contains no brace token at all. Returns a
    ``SourceKind.MACRO`` source when a token is present but unresolvable, which happens
    for an unresolved ``{VAR}`` workflow variable: variable substitution normally
    runs during ``aprocess()``, but it can be disabled per-parameter or engine-wide,
    and an unresolved token must never be mistaken for a path.
    """
    if not _HAS_BRACE_TOKEN.search(locator):
        return None

    unresolved = {
        "kind": SourceKind.MACRO,
        "value": locator,
        "format": _extension_of(locator),
        "width": None,
        "height": None,
        "byte_count": None,
        "is_pattern": False,
        "raw": locator,
    }

    try:
        parsed = ParsedMacro(locator)
    except MacroSyntaxError:
        logger.debug("Value contains braces but is not a valid macro: %s", locator)
        return unresolved

    result = GriptapeNodes.handle_request(
        GetPathForMacroRequest(
            parsed_macro=parsed,
            variables={},
            unresolved_sequence_slot_behavior=UnresolvedSequenceSlotBehavior.RENDER_SEQUENCE_PATTERN,
        )
    )
    if not isinstance(result, GetPathForMacroResultSuccess):
        return unresolved

    resolved = str(result.absolute_path)
    return {
        "kind": SourceKind.PATH,
        "value": resolved,
        "format": _extension_of(resolved),
        "width": None,
        "height": None,
        "byte_count": None,
        "is_pattern": bool(_HASH_RUN.search(resolved)),
        "raw": locator,
    }


def _source_from_locator(locator: str) -> dict[str, Any]:
    """Build a source entry from a macro template, URL, or path string."""
    macro_source = _resolve_macro(locator)
    if macro_source is not None:
        return macro_source

    kind = SourceKind.URL if locator.startswith(("http://", "https://")) else SourceKind.PATH
    return {
        "kind": kind,
        "value": locator,
        "format": _extension_of(locator),
        "width": None,
        "height": None,
        "byte_count": None,
        "is_pattern": False,
        "raw": None,
    }


def _descriptor(value_type: str, sources: list[dict[str, Any]], engine_type: str) -> dict[str, Any]:
    """Assemble the wire descriptor.

    ``colorspace`` is reserved and always None today. The engine's ``color_space``
    field is a PIL-mode channel layout (RGB, RGBA, Grayscale), not colorimetry, so
    it cannot answer whether pixels are sRGB-encoded or scene-linear. The field
    exists now because adding a nullable field later is free, while adding a
    required one is a protocol version bump.

    ``engine_type`` is diagnostic only. A host must never branch on it.
    """
    return {
        "value_type": value_type,
        "sources": sources,
        "colorspace": None,
        "engine_type": engine_type,
    }


def normalize_value(value: Any, declared_engine_type: str | None = None) -> dict[str, Any]:  # noqa: PLR0911
    """Collapse any engine parameter value into one host descriptor.

    Args:
        value: The engine-side value. Artifact instance, string, bytes, list, or scalar.
        declared_engine_type: The port's declared type name, when known. Used to
            disambiguate bare strings, which carry no media type of their own.

    Returns:
        A descriptor whose ``value_type`` is always a member of VALUE_TYPES.
    """
    engine_type = type(value).__name__

    if value is None:
        return _descriptor(ValueType.NULL, [], engine_type)

    if isinstance(value, bool):
        return _descriptor(ValueType.BOOLEAN, [], engine_type)

    if isinstance(value, (int, float)):
        return _descriptor(ValueType.NUMBER, [], engine_type)

    if isinstance(value, bytes):
        return _descriptor(
            ValueType.FILE,
            [
                {
                    "kind": SourceKind.INLINE,
                    "value": None,
                    "format": None,
                    "width": None,
                    "height": None,
                    "byte_count": len(value),
                    "is_pattern": False,
                    "raw": None,
                }
            ],
            engine_type,
        )

    if isinstance(value, str):
        return _normalize_string(value, declared_engine_type, engine_type)

    if isinstance(value, (list, tuple)):
        return _normalize_sequence(list(value), declared_engine_type, engine_type)

    return _normalize_artifact(value, declared_engine_type, engine_type)


def _normalize_string(value: str, declared_engine_type: str | None, engine_type: str) -> dict[str, Any]:
    """A bare string is either a locator or prose. The declared type breaks the tie."""
    declared_value_type = value_type_for_engine_type(declared_engine_type)

    looks_like_locator = (
        value.startswith(("http://", "https://"))
        or "/" in value
        or "\\" in value
        or bool(_HAS_BRACE_TOKEN.search(value))
    )
    if not looks_like_locator:
        return _descriptor(
            declared_value_type if declared_value_type != ValueType.FILE else ValueType.TEXT, [], engine_type
        )

    source = _source_from_locator(value)
    # A declared media type wins over the extension: the port author knew better.
    if declared_value_type in {ValueType.IMAGE, ValueType.VIDEO}:
        return _descriptor(declared_value_type, [source], engine_type)
    return _descriptor(_value_type_for_extension(source["format"]), [source], engine_type)


def _normalize_sequence(items: list[Any], declared_engine_type: str | None, engine_type: str) -> dict[str, Any]:
    """Flatten a list of values into one descriptor with many sources.

    A still and an image sequence share a host type and differ only in source count,
    so adding sequence support later does not add a value type.
    """
    if not items:
        return _descriptor(ValueType.NULL, [], engine_type)

    sources: list[dict[str, Any]] = []
    value_types: list[str] = []
    for item in items:
        inner = normalize_value(item, declared_engine_type)
        sources.extend(inner["sources"])
        if inner["value_type"] not in {ValueType.NULL, ValueType.TEXT}:
            value_types.append(inner["value_type"])

    if not value_types:
        return _descriptor(ValueType.FILE, sources, engine_type)
    if len(set(value_types)) > 1:
        logger.warning("Mixed host types in one list (%s); reporting GTFile.", sorted(set(value_types)))
        return _descriptor(ValueType.FILE, sources, engine_type)
    return _descriptor(value_types[0], sources, engine_type)


def _normalize_artifact(value: Any, declared_engine_type: str | None, engine_type: str) -> dict[str, Any]:
    """Normalize an artifact instance by its class name, then by its payload shape."""
    # ListArtifact and friends expose their children on .value as a list.
    inner_value = getattr(value, "value", None)
    if isinstance(inner_value, (list, tuple)):
        merged = _normalize_sequence(list(inner_value), declared_engine_type, engine_type)
        return _descriptor(merged["value_type"], merged["sources"], engine_type)

    value_type = value_type_for_engine_type(engine_type)

    if isinstance(inner_value, bytes):
        source = {
            "kind": SourceKind.INLINE,
            "value": None,
            "format": getattr(value, "format", None),
            "width": getattr(value, "width", None),
            "height": getattr(value, "height", None),
            "byte_count": len(inner_value),
            "is_pattern": False,
            "raw": None,
        }
        return _descriptor(value_type, [source], engine_type)

    if isinstance(inner_value, str) and inner_value:
        source = _source_from_locator(inner_value)
        # An unrecognized artifact class still yields a usable locator; classify it
        # by extension rather than reporting an opaque GTFile.
        if value_type == ValueType.FILE:
            value_type = _value_type_for_extension(source["format"])
        return _descriptor(value_type, [source], engine_type)

    return _descriptor(ValueType.FILE, [], engine_type)
