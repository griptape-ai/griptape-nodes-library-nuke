"""Normalize engine values into the host protocol's closed type set."""

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

# Control parameters carry no data and are omitted from descriptions and events.
CONTROL_PARAM_TYPE = "parametercontroltype"

# Braces alone cannot distinguish project macros from workflow variables.
_HAS_BRACE_TOKEN = re.compile(r"\{[^{}]*\}")

_HASH_RUN = re.compile(r"#+")

# Recognizes POSIX, drive-letter, and UNC absolute paths.
_ABSOLUTE_PATH_PREFIX = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")

# Unknown artifact types map to GTFile; other unknown types map to GTText.
ENGINE_TYPE_TO_VALUE_TYPE = {
    "ImageArtifact": ValueType.IMAGE,
    "ImageUrlArtifact": ValueType.IMAGE,
    # Both engine sequence names map to an image with multiple sources.
    "ImageSequenceArtifact": ValueType.IMAGE,
    "Sequence": ValueType.IMAGE,
    "VideoUrlArtifact": ValueType.MOVIE,
    "str": ValueType.TEXT,
    "string": ValueType.TEXT,
    "int": ValueType.NUMBER,
    "float": ValueType.NUMBER,
    "bool": ValueType.BOOL,
}

# Strip the engine's ``list[T]`` wrapper before mapping the element type.
_LIST_TYPE = re.compile(r"^list\[(.+)\]$")


def value_type_for_engine_type(engine_type: str | None) -> str:
    """Map a declared type before a runtime value is available."""
    if engine_type is None:
        return ValueType.TEXT

    list_match = _LIST_TYPE.match(engine_type)
    if list_match is not None:
        return value_type_for_engine_type(list_match.group(1))

    mapped = ENGINE_TYPE_TO_VALUE_TYPE.get(engine_type)
    if mapped is not None:
        return mapped
    if engine_type.endswith("Artifact"):
        return ValueType.FILE
    return ValueType.TEXT


def _extension_of(locator: str) -> str | None:
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
    """Unknown extensions map to GTFile rather than a guessed format."""
    if extension in IMAGE_EXTENSIONS:
        return ValueType.IMAGE
    if extension in VIDEO_EXTENSIONS:
        return ValueType.MOVIE
    return ValueType.FILE


def _resolve_macro(locator: str) -> dict[str, Any] | None:
    """Unresolved sequence slots remain Nuke-readable hash patterns."""
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

    # Nuke's TCL layer treats backslashes as escapes.
    resolved = str(result.absolute_path).replace("\\", "/")
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
    macro_source = _resolve_macro(locator)
    if macro_source is not None:
        return macro_source

    if locator.startswith(("http://", "https://")):
        return {
            "kind": SourceKind.URL,
            "value": locator,
            "format": _extension_of(locator),
            "width": None,
            "height": None,
            "byte_count": None,
            "is_pattern": False,
            "raw": None,
        }

    # Nuke's TCL layer treats backslashes as escapes.
    normalized = locator.replace("\\", "/")
    return {
        "kind": SourceKind.PATH,
        "value": normalized,
        "format": _extension_of(normalized),
        "width": None,
        "height": None,
        "byte_count": None,
        "is_pattern": False,
        "raw": None,
    }


def _descriptor(value_type: str, sources: list[dict[str, Any]], engine_type: str, value: Any = None) -> dict[str, Any]:
    """``colorspace`` is reserved because the engine exposes channel layout, not colorimetry.

    ``value`` carries scalars, which have no locator to point at and are otherwise unreadable.
    Sourced types leave it null: bytes stay in the engine and a path belongs in ``sources``.
    """
    return {
        "value_type": value_type,
        "value": value,
        "sources": sources,
        "colorspace": None,
        "engine_type": engine_type,
    }


def normalize_value(value: Any, declared_engine_type: str | None = None) -> dict[str, Any]:  # noqa: PLR0911
    engine_type = type(value).__name__

    if value is None:
        return _descriptor(ValueType.NULL, [], engine_type)

    if isinstance(value, bool):
        return _descriptor(ValueType.BOOL, [], engine_type, value)

    if isinstance(value, (int, float)):
        return _descriptor(ValueType.NUMBER, [], engine_type, value)

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

    if isinstance(value, dict):
        return _normalize_artifact_dict(value, declared_engine_type)

    return _normalize_artifact(value, declared_engine_type, engine_type)


# Media and file types require a source.
_SOURCED_VALUE_TYPES = frozenset({ValueType.IMAGE, ValueType.MOVIE, ValueType.FILE})


def _sourceless_descriptor(value_type: str, engine_type: str, value: Any = None) -> dict[str, Any]:
    """Downgrade sourceless media and file values to text."""
    return _descriptor(ValueType.TEXT if value_type in _SOURCED_VALUE_TYPES else value_type, [], engine_type, value)


def _classify_locator_source(source: dict[str, Any], declared_value_type: str, engine_type: str) -> dict[str, Any]:
    if declared_value_type in {ValueType.IMAGE, ValueType.MOVIE}:
        return _descriptor(declared_value_type, [source], engine_type)
    return _descriptor(_value_type_for_extension(source["format"]), [source], engine_type)


def _normalize_string(value: str, declared_engine_type: str | None, engine_type: str) -> dict[str, Any]:
    """Only URLs, absolute paths, resolvable macros, and relative paths with extensions are locators."""
    declared_value_type = value_type_for_engine_type(declared_engine_type)

    if _HAS_BRACE_TOKEN.search(value):
        macro_source = _resolve_macro(value)
        if macro_source is None:
            msg = "_HAS_BRACE_TOKEN matched but _resolve_macro found no brace token"
            raise AssertionError(msg)
        # Keep unresolved macros only when their extension or absolute shape identifies a locator.
        resolved_to_path = macro_source["kind"] == SourceKind.PATH
        if resolved_to_path or macro_source["format"] is not None or _ABSOLUTE_PATH_PREFIX.match(value):
            return _classify_locator_source(macro_source, declared_value_type, engine_type)
        return _sourceless_descriptor(declared_value_type, engine_type, value)

    if value.startswith(("http://", "https://")) or _ABSOLUTE_PATH_PREFIX.match(value):
        return _classify_locator_source(_source_from_locator(value), declared_value_type, engine_type)

    # A relative locator needs both a separator and an extension to distinguish it from prose.
    if ("/" in value or "\\" in value) and _extension_of(value) is not None:
        return _classify_locator_source(_source_from_locator(value), declared_value_type, engine_type)

    return _sourceless_descriptor(declared_value_type, engine_type, value)


def _normalize_sequence(items: list[Any], declared_engine_type: str | None, engine_type: str) -> dict[str, Any]:
    """A sequence uses one value type and multiple sources."""
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
        if not sources:
            return _sourceless_descriptor(ValueType.FILE, engine_type)
        return _descriptor(ValueType.FILE, sources, engine_type)
    if len(set(value_types)) > 1:
        logger.warning("Mixed host types in one list (%s); reporting GTFile.", sorted(set(value_types)))
        return _descriptor(ValueType.FILE, sources, engine_type)
    return _descriptor(value_types[0], sources, engine_type)


def _normalize_artifact_dict(value: dict[str, Any], declared_engine_type: str | None) -> dict[str, Any]:
    """Reads hand back serialized artifacts, where attribute access finds no locator at all.

    Keyed by the dict's own ``type`` rather than the declared one, which is what the engine says
    the value is. A dict that is not an artifact has no locator to find and stays text.
    """
    engine_type = str(value.get("type") or declared_engine_type or "dict")
    inner_value = value.get("value")
    if inner_value is None:
        return _sourceless_descriptor(value_type_for_engine_type(engine_type), engine_type)

    inner = normalize_value(inner_value, engine_type)
    return _descriptor(inner["value_type"], inner["sources"], engine_type, inner["value"])


def _normalize_artifact(value: Any, declared_engine_type: str | None, engine_type: str) -> dict[str, Any]:
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
        # Unknown artifact classes are classified by locator extension.
        if value_type == ValueType.FILE:
            value_type = _value_type_for_extension(source["format"])
        # Text values must not carry locators that a host would try to open.
        if value_type not in _SOURCED_VALUE_TYPES:
            return _sourceless_descriptor(value_type, engine_type, inner_value)
        return _descriptor(value_type, [source], engine_type)

    return _sourceless_descriptor(ValueType.FILE, engine_type)
