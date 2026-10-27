"""Normalize engine values into the host protocol's closed type set."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from griptape_nodes.common.macro_parser import ParsedMacro
from griptape_nodes.common.macro_parser.exceptions import MacroSyntaxError
from griptape_nodes.retained_mode.events.project_events import (
    GetPathForMacroRequest,
    GetPathForMacroResultSuccess,
    UnresolvedSequenceSlotBehavior,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.protocol import ValueType

try:
    from griptape_nodes.serialization import values as engine_values  # pyright: ignore[reportMissingImports]
except ImportError:
    engine_values = None

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

_SCALAR_TYPE_TO_VALUE_TYPE = {
    "str": ValueType.TEXT,
    "string": ValueType.TEXT,
    "int": ValueType.INT,
    "float": ValueType.FLOAT,
    "bool": ValueType.BOOL,
}


@dataclass(frozen=True)
class _ClassReading:
    """The host type a class declares, and which field of its state holds the value a host reads."""

    value_type: str
    field: str = "value"
    holds_bytes: bool = False


# Keyed by class name, so a library's class needs no import, and a griptape artifact is no more
# special than a library's dataclass. Unknown classes read their "value" field, and their declared
# host type is GTFile for an artifact name and GTText otherwise.
_CLASS_READINGS = {
    "ImageArtifact": _ClassReading(ValueType.IMAGE, holds_bytes=True),
    "ImageUrlArtifact": _ClassReading(ValueType.IMAGE),
    "ImageSequenceArtifact": _ClassReading(ValueType.IMAGE),
    "Sequence": _ClassReading(ValueType.IMAGE),
    "VideoArtifact": _ClassReading(ValueType.MOVIE),
    "VideoUrlArtifact": _ClassReading(ValueType.MOVIE),
    "BlobArtifact": _ClassReading(ValueType.FILE, holds_bytes=True),
    "AudioArtifact": _ClassReading(ValueType.FILE, holds_bytes=True),
    # griptape-nodes-library-openexr's descriptor.
    "EXRPartArtifact": _ClassReading(ValueType.IMAGE, field="file_path"),
}
_DEFAULT_VALUE_FIELD = "value"

# Strip the engine's ``list[T]`` wrapper before mapping the element type.
_LIST_TYPE = re.compile(r"^list\[(.+)\]$")

SEQUENCE_ENGINE_TYPE = "Sequence"

# ImageSequenceArtifact predates the engine's Sequence and holds bare frame paths with no pattern.
_LIST_ENGINE_TYPES = frozenset({"list", "ImageSequenceArtifact", "ListArtifact"})

# Every frame token the engine's scanner accepts. Nuke reads only `#` and `%0Nd`.
_FRAME_TOKEN = re.compile(r"#+|%0?\d*d|@+|\$F\d*")

_WILDCARD_ENGINE_TYPES = frozenset({"any", "all"})

_SOURCED_VALUE_TYPES = frozenset({ValueType.IMAGE, ValueType.MOVIE, ValueType.FILE})

MEDIA_ENTRY_FIELDS = frozenset({"path", "format", "first", "last"})

# The engine value codec's tags. A tagged value's state sits beside "$type" or under "$value".
TYPE_KEY = "$type"
VALUE_KEY = "$value"
_BYTES_TYPE_NAMES = frozenset({"builtins:bytes", "builtins:bytearray"})


@dataclass(frozen=True)
class _EngineObject:
    """An engine value with fields, named by its class so every kind is classified the same way."""

    class_name: str
    state: dict[str, Any]


class UnrepresentableValueError(ValueError):
    """Raised when this protocol cannot represent a value."""


def value_type_for_engine_type(engine_type: str | None) -> str:
    """Map a declared type, or a list's element type, before a runtime value is available."""
    if engine_type is None:
        return ValueType.TEXT

    list_match = _LIST_TYPE.match(engine_type)
    if list_match is not None:
        return value_type_for_engine_type(list_match.group(1))

    scalar = _SCALAR_TYPE_TO_VALUE_TYPE.get(engine_type)
    if scalar is not None:
        return scalar
    reading = _CLASS_READINGS.get(engine_type)
    if reading is not None:
        return reading.value_type
    if engine_type.endswith("Artifact"):
        return ValueType.FILE
    return ValueType.TEXT


def is_list_type(engine_type: str | None) -> bool | None:
    """None means the declaration is silent, so each value decides for itself."""
    if not engine_type or engine_type.lower() in _WILDCARD_ENGINE_TYPES:
        return None
    return engine_type in _LIST_ENGINE_TYPES or _LIST_TYPE.match(engine_type) is not None


def is_sequence_type(engine_type: str | None) -> bool:
    """True for a declared ``Sequence`` or a list of them."""
    if not engine_type:
        return False
    list_match = _LIST_TYPE.match(engine_type)
    return (list_match.group(1) if list_match else engine_type) == SEQUENCE_ENGINE_TYPE


def normalize_value(value: Any, declared_engine_type: str | None = None) -> dict[str, Any]:
    """Raises UnrepresentableValueError when the value has no host form."""
    if isinstance(value, (bytes, bytearray)):
        msg = "It holds raw bytes the engine never saved to a file."
        raise UnrepresentableValueError(msg)

    plain = _plain_value(value)
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


def _plain_value(value: Any) -> Any:
    """The value as plain data, with each object as an ``_EngineObject`` once untagged."""
    if engine_values is None:
        # Engines before 0.104 have no value codec, and their safe_unstructure still calls to_dict().
        # Imported here because later engines deprecate it.
        from griptape_nodes.retained_mode.events.event_converter import safe_unstructure  # noqa: PLC0415

        return safe_unstructure(value)
    try:
        return _untagged(engine_values.encode_value(value))
    except engine_values.ValueEncodeError as e:
        raise UnrepresentableValueError(str(e)) from e


def _untagged(data: Any) -> Any:
    """Replace the codec's ``$type`` tags with plain data, keeping an object's class name."""
    if isinstance(data, list):
        return [_untagged(item) for item in data]
    if not isinstance(data, dict):
        return data
    if TYPE_KEY not in data:
        return {key: _untagged(item) for key, item in data.items()}
    tag = data[TYPE_KEY]
    if tag in _BYTES_TYPE_NAMES:
        msg = "It holds raw bytes the engine never saved to a file."
        raise UnrepresentableValueError(msg)
    if VALUE_KEY not in data:
        # The tag is "module:QualName"; a nested class's qualname is dotted.
        class_name = str(tag).rsplit(":", 1)[-1].rsplit(".", 1)[-1]
        return _EngineObject(class_name, {key: _untagged(item) for key, item in data.items() if key != TYPE_KEY})
    state = data[VALUE_KEY]
    if tag == "builtins:dict" and isinstance(state, dict):
        # A wrapped dict: its own "$type" key is data, not a tag.
        return {key: _untagged(item) for key, item in state.items()}
    if tag == "builtins:float":
        return float(state)
    return _untagged(state)


def _descriptor(value_type: str, value: Any, engine_type: str) -> dict[str, Any]:
    return {"value_type": value_type, "value": value, "engine_type": engine_type}


def _as_object(plain: Any) -> _EngineObject | None:
    """Untagged dicts come from a serialized artifact or an engine without the value codec."""
    if isinstance(plain, _EngineObject):
        return plain
    if not isinstance(plain, dict):
        return None
    if _is_sequence(plain):
        return _EngineObject(SEQUENCE_ENGINE_TYPE, plain)
    if plain.get("type"):
        return _EngineObject(str(plain["type"]), plain)
    return None


def _value_field(class_name: str) -> str:
    reading = _CLASS_READINGS.get(class_name)
    return reading.field if reading else _DEFAULT_VALUE_FIELD


def _engine_type(value: Any, plain: Any, declared_engine_type: str | None) -> str:
    engine_object = _as_object(plain)
    if engine_object is not None:
        return engine_object.class_name
    if isinstance(plain, dict):
        return declared_engine_type or "dict"
    return type(value).__name__


def _list_items(plain: Any) -> list[Any] | None:
    if isinstance(plain, (list, tuple)):
        return list(plain)
    engine_object = _as_object(plain)
    if engine_object is None or engine_object.class_name == SEQUENCE_ENGINE_TYPE:
        return None
    inner = engine_object.state.get(_value_field(engine_object.class_name))
    return list(inner) if isinstance(inner, list) else None


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
    engine_object = _as_object(item)
    if engine_object is not None:
        return _normalize_object(engine_object, declared_engine_type)
    if isinstance(item, dict):
        msg = "It holds a dict, which this protocol has no type for."
        raise UnrepresentableValueError(msg)
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


def nuke_frame_pattern(pattern: str, padding: int | None) -> str:
    """Rewrite a scanner frame token into the `#` form Nuke reads."""
    return _FRAME_TOKEN.sub("#" * max(padding or 0, 1), pattern, count=1)


def _is_sequence(value: dict[str, Any]) -> bool:
    return "pattern" in value and "entries" in value


def _normalize_sequence(value: dict[str, Any], declared_engine_type: str | None) -> tuple[str | None, Any]:
    """One entry for the whole sequence, so a host builds one Read rather than one per frame."""
    pattern = value.get("pattern")
    # An empty scan result has no pattern and no entries.
    if not pattern or not value.get("entries"):
        return None, None
    filename = nuke_frame_pattern(str(pattern), value.get("padding"))
    directory = value.get("directory")
    path = f"{directory}/{filename}" if directory else filename
    value_type, entry = _normalize_string(path, declared_engine_type)
    if not isinstance(entry, dict):
        msg = f"It holds a sequence at '{path}', which is not a local path."
        raise UnrepresentableValueError(msg)
    return value_type, {**entry, "first": value.get("first"), "last": value.get("last")}


def _normalize_object(engine_object: _EngineObject, declared_engine_type: str | None) -> tuple[str | None, Any]:
    """Keyed by the object's own class, which is what the engine says the value is."""
    class_name = engine_object.class_name
    if class_name == SEQUENCE_ENGINE_TYPE:
        return _normalize_sequence(engine_object.state, declared_engine_type)
    reading = _CLASS_READINGS.get(class_name)
    if reading is not None and reading.holds_bytes:
        # Serialized, these bytes are base64 text indistinguishable from prose.
        msg = f"It holds {class_name} bytes the engine never saved to a file."
        raise UnrepresentableValueError(msg)
    field = _value_field(class_name)
    if field not in engine_object.state:
        msg = f"It holds a {class_name}, which this protocol has no type for."
        raise UnrepresentableValueError(msg)

    inner = engine_object.state[field]
    if isinstance(inner, str):
        return _normalize_string(inner, class_name)
    if isinstance(inner, (dict, _EngineObject)):
        msg = f"It holds a {class_name} wrapping a dict, which this protocol has no type for."
        raise UnrepresentableValueError(msg)
    return _normalize_item(inner, declared_engine_type)


def _normalize_string(value: str, declared_engine_type: str | None) -> tuple[str | None, Any]:
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
    extension = _extension_of(path)
    if declared_value_type in {ValueType.IMAGE, ValueType.MOVIE}:
        value_type = declared_value_type
    elif extension in IMAGE_EXTENSIONS:
        value_type = ValueType.IMAGE
    elif extension in VIDEO_EXTENSIONS:
        value_type = ValueType.MOVIE
    else:
        value_type = ValueType.FILE
    return value_type, {"path": path, "format": extension, "first": None, "last": None}


def _extension_of(locator: str) -> str | None:
    name = locator.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in name:
        return None
    extension = name.rsplit(".", 1)[-1].lower()
    if not extension or not extension.isalnum():
        return None
    return extension


def _resolve_macro(value: str) -> str | None:
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
