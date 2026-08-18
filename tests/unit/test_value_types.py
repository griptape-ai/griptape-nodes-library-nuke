"""Tests for the value normalizer.

Asserts on narrowed output rather than on "it did not raise". An earlier version of this
layer silently produced zero ports for every workflow while every call still reported
success, which is the failure mode these tests exist to catch.
"""

from __future__ import annotations

from typing import Any

import pytest
from griptape.artifacts import (
    BlobArtifact,
    GenericArtifact,
    ImageArtifact,
    ImageUrlArtifact,
    ListArtifact,
    VideoUrlArtifact,
)

from nuke_host_api import value_types
from nuke_host_api.protocol import VALUE_TYPES, SourceKind, ValueType

STATIC_URL = "http://localhost:8124/workspace/static_files/render.png"


@pytest.mark.parametrize(
    ("engine_type", "expected"),
    [
        ("ImageArtifact", ValueType.IMAGE),
        ("ImageUrlArtifact", ValueType.IMAGE),
        ("VideoUrlArtifact", ValueType.VIDEO),
        ("str", ValueType.TEXT),
        ("int", ValueType.NUMBER),
        ("float", ValueType.NUMBER),
        ("bool", ValueType.BOOLEAN),
        # Unknown artifact classes degrade to a file rather than leaking the engine name.
        ("AudioUrlArtifact", ValueType.FILE),
        ("SomethingInventedNextRelease", ValueType.TEXT),
        (None, ValueType.TEXT),
    ],
)
def test_engine_type_names_map_into_the_closed_set(engine_type: str | None, expected: str) -> None:
    assert value_types.value_type_for_engine_type(engine_type) == expected


@pytest.mark.parametrize(
    ("value", "declared", "expected"),
    [
        (ImageUrlArtifact(STATIC_URL), "ImageUrlArtifact", ValueType.IMAGE),
        (VideoUrlArtifact("http://x/plate.mov"), "VideoUrlArtifact", ValueType.VIDEO),
        (ImageArtifact(value=b"\x89PNG", format="png", width=4, height=2), "ImageArtifact", ValueType.IMAGE),
        ("/mnt/show/plate.exr", "str", ValueType.IMAGE),
        ("/mnt/show/plate.mov", "str", ValueType.VIDEO),
        ("/mnt/show/notes.txt", "str", ValueType.FILE),
        ("a hazy afternoon", "str", ValueType.TEXT),
        ("3/4 cup", "str", ValueType.TEXT),
        ("aspect 16/9", "str", ValueType.TEXT),
        (BlobArtifact(value=b"\x00\x01"), "BlobArtifact", ValueType.FILE),
        (None, "ImageUrlArtifact", ValueType.NULL),
        (True, "bool", ValueType.BOOLEAN),
        (23.976, "float", ValueType.NUMBER),
        (7, "int", ValueType.NUMBER),
    ],
)
def test_values_normalize_into_the_closed_set(value: Any, declared: str, expected: str) -> None:
    descriptor = value_types.normalize_value(value, declared)
    assert descriptor["value_type"] == expected
    assert descriptor["value_type"] in VALUE_TYPES


def test_every_descriptor_reports_a_member_of_the_closed_set() -> None:
    """No input may produce a type a host has no case for."""
    inputs: list[Any] = [
        None,
        "",
        "prose",
        b"bytes",
        0,
        False,
        [],
        {},
        object(),
        ListArtifact([]),
        GenericArtifact("https://x/y.jpg"),
    ]
    for value in inputs:
        assert value_types.normalize_value(value)["value_type"] in VALUE_TYPES


def test_bool_is_not_reported_as_a_number() -> None:
    """bool is a subclass of int in Python, so order of checks matters."""
    assert value_types.normalize_value(True)["value_type"] == ValueType.BOOLEAN
    assert value_types.normalize_value(1)["value_type"] == ValueType.NUMBER


def test_format_is_never_guessed() -> None:
    """A URL with no extension must report null, not a plausible default.

    `_artifact_to_path` in the Nuke library defaults to `.png` here, which mislabels a
    JPEG served without an extension.
    """
    descriptor = value_types.normalize_value(ImageUrlArtifact("https://cdn.example.com/asset"), "ImageUrlArtifact")
    assert descriptor["value_type"] == ValueType.IMAGE
    assert descriptor["sources"][0]["format"] is None


def test_declared_type_outranks_the_extension() -> None:
    """The port author knew the media type; the filename may not carry it."""
    descriptor = value_types.normalize_value("/mnt/show/no_extension", "ImageUrlArtifact")
    assert descriptor["value_type"] == ValueType.IMAGE


def test_unknown_artifact_class_is_classified_by_extension() -> None:
    """GenericArtifact means nothing to the contract, but its locator still does.

    ImageUrlArtifact, VideoUrlArtifact, BlobArtifact and GenericArtifact are structurally
    identical, all carrying a single `value`, so the class name is the only discriminator
    and it has to be allowed to be useless.
    """
    descriptor = value_types.normalize_value(GenericArtifact("https://cdn.example.com/still.jpg"))
    assert descriptor["value_type"] == ValueType.IMAGE
    assert descriptor["sources"][0]["format"] == "jpg"


def test_locator_kinds_are_explicit() -> None:
    """A host must never have to sniff whether a string is a URL or a path."""
    assert value_types.normalize_value(STATIC_URL, "str")["sources"][0]["kind"] == SourceKind.URL
    assert value_types.normalize_value("/mnt/show/plate.exr", "str")["sources"][0]["kind"] == SourceKind.PATH
    inline = value_types.normalize_value(ImageArtifact(value=b"\x89PNG", format="png", width=1, height=1))
    assert inline["sources"][0]["kind"] == SourceKind.INLINE
    assert inline["sources"][0]["byte_count"] == 4


def test_a_literal_windows_path_is_slash_normalized_without_going_through_a_macro() -> None:
    """CLAUDE.md's forward-slash rule applies to a plain path string, not only a macro-resolved one."""
    descriptor = value_types.normalize_value("C:\\workspace\\outputs\\render.png", "str")
    source = descriptor["sources"][0]
    assert source["value"] == "C:/workspace/outputs/render.png"
    assert "\\" not in source["value"]


def test_a_frame_list_is_one_image_with_many_sources() -> None:
    """Sequences are source count, not a value type, so they cost no version bump."""
    frames = ListArtifact([ImageUrlArtifact(f"http://x/frame.{n:04d}.exr") for n in (1, 2, 3)])
    descriptor = value_types.normalize_value(frames, "ImageUrlArtifact")
    assert descriptor["value_type"] == ValueType.IMAGE
    assert len(descriptor["sources"]) == 3
    assert {source["format"] for source in descriptor["sources"]} == {"exr"}


def test_a_mixed_list_degrades_rather_than_picking_a_winner() -> None:
    mixed = ListArtifact([ImageUrlArtifact("http://x/a.png"), VideoUrlArtifact("http://x/b.mov")])
    assert value_types.normalize_value(mixed)["value_type"] == ValueType.FILE


def test_an_empty_list_is_null_not_an_empty_image() -> None:
    assert value_types.normalize_value(ListArtifact([]))["value_type"] == ValueType.NULL


def test_a_slash_alone_does_not_make_prose_a_file() -> None:
    """A slash proves nothing about media type; without an extension the declared type wins, and no fake source is attached."""
    assert value_types.normalize_value("3/4 cup", "str")["value_type"] == ValueType.TEXT
    assert value_types.normalize_value("3/4 cup", "str")["sources"] == []
    assert value_types.normalize_value("aspect 16/9", "str")["value_type"] == ValueType.TEXT
    assert value_types.normalize_value("aspect 16/9", "str")["sources"] == []


@pytest.mark.parametrize(
    ("value", "declared", "expected_type", "expect_source"),
    [
        # Genuine locator shapes: extension known or not, the source is real and is kept.
        ("/mnt/show/plate.exr", "str", ValueType.IMAGE, True),
        ("/mnt/show/notes.txt", "str", ValueType.FILE, True),
        ("/mnt/show/renders", "str", ValueType.FILE, True),
        ("https://host/asset", "str", ValueType.FILE, True),
        ("/render/mix_final", "AudioUrlArtifact", ValueType.FILE, True),
        # A relative path is the ordinary form in a Nuke script, so an extension alongside a
        # separator is enough to make it a locator.
        ("shots/plate.exr", "str", ValueType.IMAGE, True),
        ("renders/out.mov", "str", ValueType.VIDEO, True),
        ("notes/readme.txt", "str", ValueType.FILE, True),
        # Prose that merely contains a slash: no locator shape, so the declared type wins
        # and no source is manufactured.
        ("3/4 cup", "str", ValueType.TEXT, False),
        ("aspect 16/9", "str", ValueType.TEXT, False),
        ("plain prose here", "str", ValueType.TEXT, False),
        # A separator with no extension and no absolute shape stays prose.
        ("shots/plate", "str", ValueType.TEXT, False),
    ],
)
def test_locator_fallback_matrix(value: str, declared: str, expected_type: str, expect_source: bool) -> None:
    """Only a genuine locator shape keeps a source: a URL, an absolute path, or a relative path carrying an extension."""
    descriptor = value_types.normalize_value(value, declared)
    assert descriptor["value_type"] == expected_type
    if expect_source:
        assert len(descriptor["sources"]) == 1
        assert descriptor["sources"][0]["value"] == value
    else:
        assert descriptor["sources"] == []


SOURCELESS_VALUE_TYPES = {ValueType.TEXT, ValueType.NUMBER, ValueType.BOOLEAN, ValueType.NULL}


@pytest.mark.parametrize(
    "declared",
    ["str", "int", "ImageUrlArtifact", "VideoUrlArtifact", "AudioUrlArtifact", "GenericArtifact", None],
)
@pytest.mark.parametrize(
    "value",
    [
        "just prose",
        "",
        "3/4 cup",
        "render {frame} of the shot",
        "shots/plate",
        "/mnt/show/plate.exr",
        "shots/plate.exr",
        "https://host/asset",
        None,
        7,
        True,
        ["note one", "note two"],
        ["/a/one.exr", "/a/two.exr"],
        object(),
    ],
)
def test_a_media_or_file_type_never_arrives_without_a_source(value: Any, declared: str | None) -> None:
    """GTImage, GTVideo and GTFile promise a host somewhere to get bytes, so they must carry a source.

    Both docs publish the inverse rule too: only GTText, GTNumber, GTBoolean and GTNull arrive
    sourceless. A declared media type describes what a port is for, not what a value turned out
    to be, so prose on an image port must not be announced as an image a host can open.
    """
    descriptor = value_types.normalize_value(value, declared)
    value_type = descriptor["value_type"]
    has_source = bool(descriptor["sources"])

    if value_type in SOURCELESS_VALUE_TYPES:
        assert not has_source, f"{value_type} carried a source for {value!r} declared {declared!r}"
    else:
        assert has_source, f"{value_type} carried no source for {value!r} declared {declared!r}"


def test_colorspace_is_present_and_reserved() -> None:
    """Reserved now so that filling it in later is additive rather than a version bump.

    The engine's own `color_space` is a PIL mode (RGB, RGBA, Grayscale), which is channel
    layout rather than a transfer function, so it cannot answer sRGB versus scene-linear.
    """
    descriptor = value_types.normalize_value(ImageUrlArtifact(STATIC_URL), "ImageUrlArtifact")
    assert "colorspace" in descriptor
    assert descriptor["colorspace"] is None


def test_engine_type_is_carried_for_diagnostics() -> None:
    descriptor = value_types.normalize_value(ImageUrlArtifact(STATIC_URL), "ImageUrlArtifact")
    assert descriptor["engine_type"] == "ImageUrlArtifact"


def test_descriptor_shape_is_stable_across_inputs() -> None:
    """Every descriptor carries the same keys, so a host can parse one shape."""
    expected_top = {"value_type", "sources", "colorspace", "engine_type"}
    expected_source = {"kind", "value", "format", "width", "height", "byte_count", "is_pattern", "raw"}
    for value in [None, "prose", "/a/b.exr", b"x", ImageUrlArtifact(STATIC_URL), 1, True]:
        descriptor = value_types.normalize_value(value)
        assert set(descriptor) == expected_top
        for source in descriptor["sources"]:
            assert set(source) == expected_source
