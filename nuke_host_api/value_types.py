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

# A leading '/', a Windows drive prefix ('C:\' or 'C:/'), or a UNC prefix ('\\server\share') --
# shapes an operating system treats as absolute, regardless of what type a port declares.
_ABSOLUTE_PATH_PREFIX = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")

# Engine parameter type names mapped to host types. Unrecognized names fall back to
# GTFile when they look artifact-shaped and GTText otherwise, so a host never sees a
# type it has no case for.
ENGINE_TYPE_TO_VALUE_TYPE = {
    "ImageArtifact": ValueType.IMAGE,
    "ImageUrlArtifact": ValueType.IMAGE,
    # An image sequence is an image with many sources, so both names in use for one land on
    # GTImage rather than degrading to GTFile or GTText. "Sequence" is what this library's
    # own NukeScriptNode declares on a sequence port.
    "ImageSequenceArtifact": ValueType.IMAGE,
    "Sequence": ValueType.IMAGE,
    "VideoUrlArtifact": ValueType.MOVIE,
    "str": ValueType.TEXT,
    "string": ValueType.TEXT,
    "int": ValueType.NUMBER,
    "float": ValueType.NUMBER,
    "bool": ValueType.BOOL,
}

# A container port's declared name wraps its element type, as ``list[ImageUrlArtifact]``
# (built in the engine's ``core_types.py``). The brackets defeat both the mapping table and
# the ``Artifact`` suffix test, so the wrapper comes off before either one runs.
_LIST_TYPE = re.compile(r"^list\[(.+)\]$")


def value_type_for_engine_type(engine_type: str | None) -> str:
    """Map a declared engine parameter type name to a value type.

    Used for port metadata in describe_workflow, where only the type *name* is
    available and no value has been produced yet.

    A declared name is a hint for building a knob; the runtime descriptor's ``value_type``
    is what a host acts on. The two match exactly whenever the declared name carries media
    or scalar information. They can differ, and only by narrowing, when it does not:

    - A wildcard (``any``, ``all``) accepts anything, so this reports ``GTText`` and a host
      builds its most permissive control.
    - An artifact class this version does not map reports ``GTFile``. Its values may still
      normalize to ``GTImage`` or ``GTMovie``, because ``_normalize_artifact`` classifies an
      unrecognized class by the extension on the locator it turned out to carry, and a
      ``GenericArtifact`` holding a ``.jpg`` really is an image. Nothing here can know that
      before a value exists, and discarding it once one does would be worse.
    """
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
        return ValueType.MOVIE
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

    # Forward slashes: Nuke's TCL layer treats backslashes as escapes, so any path this
    # layer hands toward a Read node must be slash-normalized before it leaves here.
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
    """Build a source entry from a macro template, URL, or path string."""
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

    # Forward slashes: Nuke's TCL layer treats backslashes as escapes, so any path this
    # layer hands toward a Read node must be slash-normalized before it leaves here. The
    # resolved-macro branch above already does this; a literal path string needs it too.
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
        return _descriptor(ValueType.BOOL, [], engine_type)

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


# The types that only mean something alongside a source. A host reaches for bytes when it sees
# one of these, so a descriptor that claims one while carrying no source is a broken promise.
_SOURCED_VALUE_TYPES = frozenset({ValueType.IMAGE, ValueType.MOVIE, ValueType.FILE})


def _sourceless_descriptor(value_type: str, engine_type: str) -> dict[str, Any]:
    """Assemble a descriptor that carries no source, downgrading any media or file claim to text.

    Nothing here can point a host at bytes, so ``GTImage``, ``GTMovie`` and ``GTFile`` are not
    honest answers: a declared media type describes what a port is *for*, not what this value
    turned out to be. Prose on an image-declared port is still prose. ``GTText`` is the one
    type that means something without a source, so that is what a host is told, keeping the
    published rule that only GTText, GTNumber, GTBool and GTNull arrive sourceless.
    """
    return _descriptor(ValueType.TEXT if value_type in _SOURCED_VALUE_TYPES else value_type, [], engine_type)


def _classify_locator_source(source: dict[str, Any], declared_value_type: str, engine_type: str) -> dict[str, Any]:
    """Turn a confirmed locator source into a descriptor, letting a declared media type win over the extension."""
    if declared_value_type in {ValueType.IMAGE, ValueType.MOVIE}:
        return _descriptor(declared_value_type, [source], engine_type)
    return _descriptor(_value_type_for_extension(source["format"]), [source], engine_type)


def _normalize_string(value: str, declared_engine_type: str | None, engine_type: str) -> dict[str, Any]:
    """A bare string is either a locator or prose.

    Only a genuine locator shape keeps a source and gets classified by extension: a URL, an
    absolute path, a macro that actually resolved to one, or a relative path carrying an
    extension. A stray slash or brace in prose ("3/4 cup", "render {frame} of the shot") proves
    nothing about media type and must not manufacture a fake path.

    An artifact-declared value keeps that declared type when it is locator-shaped, so
    "/render/mix_final" on an audio port stays GTFile even though the extension is unknown.
    With no locator shape there is no source to hand over, so the media claim would be empty and
    collapses to text instead; see ``_sourceless_descriptor``.
    """
    declared_value_type = value_type_for_engine_type(declared_engine_type)

    if _HAS_BRACE_TOKEN.search(value):
        macro_source = _resolve_macro(value)
        if macro_source is None:
            msg = "_HAS_BRACE_TOKEN matched but _resolve_macro found no brace token"
            raise AssertionError(msg)
        # An unresolved macro (kind MACRO, not PATH) is still a real locator when it has an
        # extension the engine can read ("{VAR}/plate.exr") or is absolute-shaped
        # ("{VAR}/out" beginning with '/'); otherwise it is indistinguishable from prose that
        # happens to contain a brace ("render {frame} of the shot") and must not keep a source.
        resolved_to_path = macro_source["kind"] == SourceKind.PATH
        if resolved_to_path or macro_source["format"] is not None or _ABSOLUTE_PATH_PREFIX.match(value):
            return _classify_locator_source(macro_source, declared_value_type, engine_type)
        return _sourceless_descriptor(declared_value_type, engine_type)

    if value.startswith(("http://", "https://")) or _ABSOLUTE_PATH_PREFIX.match(value):
        return _classify_locator_source(_source_from_locator(value), declared_value_type, engine_type)

    # A relative path still names a file when it carries an extension ("shots/plate.exr"), which
    # is the ordinary form inside a Nuke script. A separator alone proves nothing, since "3/4 cup"
    # has one, so an extension has to appear alongside it. This is the same extension test the
    # macro branch above applies to an unresolved template.
    if ("/" in value or "\\" in value) and _extension_of(value) is not None:
        return _classify_locator_source(_source_from_locator(value), declared_value_type, engine_type)

    return _sourceless_descriptor(declared_value_type, engine_type)


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
        if not sources:
            return _sourceless_descriptor(ValueType.FILE, engine_type)
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
        # A class name that looks like neither a scalar nor an artifact resolves to text, and a
        # text value must not arrive carrying a locator a host would try to open.
        if value_type not in _SOURCED_VALUE_TYPES:
            return _sourceless_descriptor(value_type, engine_type)
        return _descriptor(value_type, [source], engine_type)

    return _sourceless_descriptor(ValueType.FILE, engine_type)
