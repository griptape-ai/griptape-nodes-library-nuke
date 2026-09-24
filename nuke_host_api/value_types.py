"""Normalize engine values into the host protocol's closed type set."""

from __future__ import annotations

import logging
import re
from typing import Any

from griptape_nodes.common.macro_parser import ParsedMacro
from griptape_nodes.common.macro_parser.exceptions import MacroSyntaxError
from griptape_nodes.retained_mode.events.event_converter import safe_unstructure
from griptape_nodes.retained_mode.events.project_events import (
    GetPathForMacroRequest,
    GetPathForMacroResultSuccess,
    UnresolvedSequenceSlotBehavior,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.protocol import ValueType

logger = logging.getLogger("griptape_nodes")

IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "exr", "tif", "tiff", "webp", "dpx", "tga", "hdr"})
# MXF is deliberately absent: it also wraps audio-only essence, so it stays GTFile unless a
# declared movie type says otherwise.
VIDEO_EXTENSIONS = frozenset(
    {"mp4", "mov", "avi", "mkv", "webm", "m4v", "mpg", "mpeg", "m2v", "wmv", "ogv", "mts", "m2ts", "r3d"}
)

# Control parameters carry no data and are omitted from descriptions and events.
CONTROL_PARAM_TYPE = "parametercontroltype"

# Braces alone cannot distinguish project macros from workflow variables.
_HAS_BRACE_TOKEN = re.compile(r"\{[^{}]*\}")

# Recognizes POSIX, drive-letter, and UNC absolute paths.
_ABSOLUTE_PATH_PREFIX = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")

# Unknown artifact types map to GTFile; other unknown types map to GTText.
ENGINE_TYPE_TO_VALUE_TYPE = {
    "ImageArtifact": ValueType.IMAGE,
    "ImageUrlArtifact": ValueType.IMAGE,
    "ImageSequenceArtifact": ValueType.IMAGE,
    "Sequence": ValueType.IMAGE,
    "VideoArtifact": ValueType.MOVIE,
    "VideoUrlArtifact": ValueType.MOVIE,
    "str": ValueType.TEXT,
    "string": ValueType.TEXT,
    "int": ValueType.INT,
    "float": ValueType.FLOAT,
    "bool": ValueType.BOOL,
}

# Strip the engine's ``list[T]`` wrapper before mapping the element type.
_LIST_TYPE = re.compile(r"^list\[(.+)\]$")

_LIST_ENGINE_TYPES = frozenset({"list", "Sequence", "ImageSequenceArtifact", "ListArtifact"})

# Declares nothing about cardinality, so the runtime value decides.
_WILDCARD_ENGINE_TYPES = frozenset({"any", "all"})

# griptape's BlobArtifact family. Serialized, their bytes are base64 text indistinguishable from prose.
_BYTE_ARTIFACT_TYPES = frozenset({"BlobArtifact", "ImageArtifact", "AudioArtifact"})

_SOURCED_VALUE_TYPES = frozenset({ValueType.IMAGE, ValueType.MOVIE, ValueType.FILE})

MEDIA_ENTRY_FIELDS = frozenset({"path", "format"})


class UnrepresentableValueError(ValueError):
    """A value this protocol version has no form for, reported as unavailable rather than guessed at."""


def value_type_for_engine_type(engine_type: str | None) -> str:
    """Map a declared type, or a list's element type, before a runtime value is available."""
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


def is_list_type(engine_type: str | None) -> bool | None:
    """None means the declaration is silent, so each value decides for itself."""
    if not engine_type or engine_type.lower() in _WILDCARD_ENGINE_TYPES:
        return None
    return engine_type in _LIST_ENGINE_TYPES or _LIST_TYPE.match(engine_type) is not None


def normalize_value(value: Any, declared_engine_type: str | None = None) -> dict[str, Any]:
    """Raises UnrepresentableValueError when the value has no host form."""
    if isinstance(value, (bytes, bytearray)):
        msg = "It holds raw bytes the engine never saved to a file."
        raise UnrepresentableValueError(msg)

    plain = safe_unstructure(value)
    engine_type = _engine_type(value, plain, declared_engine_type)
    declared_value_type = value_type_for_engine_type(declared_engine_type)
    items = _list_items(plain)

    is_list = is_list_type(declared_engine_type)
    if is_list is None:
        is_list = items is not None

    if not is_list:
        if items is not None:
            msg = f"It is declared as a single value but holds a list of {len(items)}."
            raise UnrepresentableValueError(msg)
        value_type, host_value = _normalize_item(plain, declared_engine_type)
        return _descriptor(value_type or declared_value_type, host_value, engine_type)

    if items is None:
        items = [] if plain in (None, "") else [plain]
    normalized = [_normalize_item(item, declared_engine_type) for item in items]
    value_type = _merge_value_types([vt for vt, _ in normalized if vt is not None], declared_value_type)
    return _descriptor(value_type, [host_value for _, host_value in normalized], engine_type)


def engine_value(value: Any) -> Any:
    """Unwrap media entries so a host can send back exactly what it read."""
    if isinstance(value, list):
        return [engine_value(item) for item in value]
    if isinstance(value, dict) and "path" in value and set(value) <= MEDIA_ENTRY_FIELDS:
        return value["path"]
    return value


def _descriptor(value_type: str, value: Any, engine_type: str) -> dict[str, Any]:
    return {"value_type": value_type, "value": value, "engine_type": engine_type}


def _engine_type(value: Any, plain: Any, declared_engine_type: str | None) -> str:
    if isinstance(plain, dict):
        return str(plain.get("type") or declared_engine_type or "dict")
    return type(value).__name__


def _list_items(plain: Any) -> list[Any] | None:
    """Recognize every list shape a read hands back: plain lists, ListArtifacts, and Sequences."""
    if isinstance(plain, (list, tuple)):
        return list(plain)
    if not isinstance(plain, dict):
        return None
    entries = plain.get("entries")
    if isinstance(entries, list) and "pattern" in plain:
        return [entry.get("path") if isinstance(entry, dict) else entry for entry in entries]
    inner = plain.get("value")
    if plain.get("type") and isinstance(inner, list):
        return list(inner)
    return None


def _merge_value_types(value_types: list[str], declared_value_type: str) -> str:
    present = set(value_types)
    if not present:
        return declared_value_type
    if len(present) == 1:
        return present.pop()
    # Ints beside floats are one numeric knob, not a type conflict.
    if present == {ValueType.INT, ValueType.FLOAT}:
        return ValueType.FLOAT
    if present <= _SOURCED_VALUE_TYPES:
        return ValueType.FILE
    msg = f"It mixes {', '.join(sorted(present))} in one list."
    raise UnrepresentableValueError(msg)


def _normalize_item(item: Any, declared_engine_type: str | None) -> tuple[str | None, Any]:
    """A None value type means unset, which takes the declared type."""
    if item is None:
        return None, None
    if isinstance(item, bool):
        return ValueType.BOOL, item
    if isinstance(item, (int, float)):
        return _numeric_value_type(item, declared_engine_type), item
    if isinstance(item, str):
        return _normalize_string(item, declared_engine_type)
    if isinstance(item, dict):
        return _normalize_artifact_dict(item, declared_engine_type)
    if isinstance(item, (list, tuple)):
        msg = "It holds a list nested inside a list."
        raise UnrepresentableValueError(msg)
    msg = f"It holds a {type(item).__name__}, which this protocol has no type for."
    raise UnrepresentableValueError(msg)


def _numeric_value_type(value: int | float, declared_engine_type: str | None) -> str:
    """A float declaration preserves a Double_Knob for later fractional values."""
    if isinstance(value, float) or value_type_for_engine_type(declared_engine_type) == ValueType.FLOAT:
        return ValueType.FLOAT
    return ValueType.INT


def _normalize_artifact_dict(value: dict[str, Any], declared_engine_type: str | None) -> tuple[str | None, Any]:
    """Keyed by the dict's own ``type``, which is what the engine says the value is."""
    artifact_type = value.get("type")
    if not artifact_type:
        msg = "It holds a dict, which this protocol has no type for."
        raise UnrepresentableValueError(msg)
    if artifact_type in _BYTE_ARTIFACT_TYPES:
        msg = f"It holds {artifact_type} bytes the engine never saved to a file."
        raise UnrepresentableValueError(msg)

    inner = value.get("value")
    if isinstance(inner, str):
        return _normalize_string(inner, str(artifact_type))
    if isinstance(inner, dict):
        msg = f"It holds a {artifact_type} wrapping a dict, which this protocol has no type for."
        raise UnrepresentableValueError(msg)
    return _normalize_item(inner, declared_engine_type)


def _normalize_string(value: str, declared_engine_type: str | None) -> tuple[str | None, Any]:
    """Only local paths become media. URLs, prose, and unresolved templates do not."""
    declared_value_type = value_type_for_engine_type(declared_engine_type)
    if not value and declared_value_type in _SOURCED_VALUE_TYPES:
        return None, None

    if _HAS_BRACE_TOKEN.search(value):
        resolved = _resolve_macro(value)
        if resolved is not None:
            return _path_entry(resolved, declared_value_type)
        if _extension_of(value) is not None or _ABSOLUTE_PATH_PREFIX.match(value):
            msg = f"It holds '{value}', a path template that did not resolve."
            raise UnrepresentableValueError(msg)
        return ValueType.TEXT, value

    if value.startswith(("http://", "https://")):
        if declared_value_type in _SOURCED_VALUE_TYPES:
            msg = f"It holds the URL '{value}', and this protocol version reports local paths only."
            raise UnrepresentableValueError(msg)
        return ValueType.TEXT, value

    # A relative locator needs both a separator and an extension to distinguish it from prose.
    is_relative_locator = ("/" in value or "\\" in value) and _extension_of(value) is not None
    if _ABSOLUTE_PATH_PREFIX.match(value) or is_relative_locator:
        # Nuke's TCL layer treats backslashes as escapes.
        return _path_entry(value.replace("\\", "/"), declared_value_type)

    return ValueType.TEXT, value


def _path_entry(path: str, declared_value_type: str) -> tuple[str, dict[str, Any]]:
    """A declared image or movie keeps its type; anything else is classified by extension."""
    extension = _extension_of(path)
    if declared_value_type in {ValueType.IMAGE, ValueType.MOVIE}:
        value_type = declared_value_type
    elif extension in IMAGE_EXTENSIONS:
        value_type = ValueType.IMAGE
    elif extension in VIDEO_EXTENSIONS:
        value_type = ValueType.MOVIE
    else:
        value_type = ValueType.FILE
    return value_type, {"path": path, "format": extension}


def _extension_of(locator: str) -> str | None:
    name = locator.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in name:
        return None
    extension = name.rsplit(".", 1)[-1].lower()
    if not extension or not extension.isalnum():
        return None
    return extension


def _resolve_macro(value: str) -> str | None:
    """None when the braces are not a macro or the macro does not resolve."""
    try:
        parsed = ParsedMacro(value)
    except MacroSyntaxError:
        logger.debug("Value contains braces but is not a valid macro: %s", value)
        return None

    # A Read node expands `###` itself, so an unfilled sequence slot is rendered rather than refused.
    result = GriptapeNodes.handle_request(
        GetPathForMacroRequest(
            parsed_macro=parsed,
            variables={},
            unresolved_sequence_slot_behavior=UnresolvedSequenceSlotBehavior.RENDER_SEQUENCE_PATTERN,
        )
    )
    if not isinstance(result, GetPathForMacroResultSuccess):
        return None
    # Nuke's TCL layer treats backslashes as escapes.
    return str(result.absolute_path).replace("\\", "/")
