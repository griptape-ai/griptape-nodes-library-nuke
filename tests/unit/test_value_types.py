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
from griptape_nodes.retained_mode.events.project_events import (
    GetPathForMacroResultFailure,
    PathResolutionFailureReason,
)

from nuke_host_api import value_types
from nuke_host_api.protocol import VALUE_TYPES, SourceKind, ValueType

STATIC_URL = "http://localhost:8124/workspace/static_files/render.png"


@pytest.fixture(autouse=True)
def _unresolvable_macros(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer macro resolution with a refusal instead of reaching the real engine.

    One parametrized value below carries a ``{frame}`` template, and resolving one is an
    engine request. Test subject here is what the normalizer does with a template it cannot
    resolve, so the engine that refuses may as well be a fake; see tests/unit/conftest.py
    for what booting the real one costs.
    """

    class RefusingEngine:
        @staticmethod
        def handle_request(request: Any) -> Any:  # noqa: ARG004
            return GetPathForMacroResultFailure(
                failure_reason=PathResolutionFailureReason.MISSING_REQUIRED_VARIABLES,
                missing_variables={"frame"},
                result_details="missing required variables",
            )

    monkeypatch.setattr(value_types, "GriptapeNodes", RefusingEngine)


@pytest.mark.parametrize(
    ("engine_type", "expected"),
    [
        ("ImageArtifact", ValueType.IMAGE),
        ("ImageUrlArtifact", ValueType.IMAGE),
        ("VideoUrlArtifact", ValueType.MOVIE),
        ("str", ValueType.TEXT),
        ("int", ValueType.NUMBER),
        ("float", ValueType.NUMBER),
        ("bool", ValueType.BOOL),
        # An image sequence is an image with many sources, under either name in use for one.
        ("Sequence", ValueType.IMAGE),
        ("ImageSequenceArtifact", ValueType.IMAGE),
        # The engine wraps a container parameter's element type, and the brackets must not defeat
        # the mapping table or the Artifact suffix test.
        ("list[ImageUrlArtifact]", ValueType.IMAGE),
        ("list[VideoUrlArtifact]", ValueType.MOVIE),
        ("list[int]", ValueType.NUMBER),
        ("list[str]", ValueType.TEXT),
        ("list[AudioUrlArtifact]", ValueType.FILE),
        # A wildcard parameter declares only that it accepts anything, so the most permissive
        # host control is the honest answer and the runtime descriptor is authoritative.
        ("any", ValueType.TEXT),
        ("all", ValueType.TEXT),
        # Unknown artifact classes degrade to a file rather than leaking the engine name.
        ("AudioUrlArtifact", ValueType.FILE),
        ("SomethingInventedNextRelease", ValueType.TEXT),
        (None, ValueType.TEXT),
    ],
)
def test_engine_type_names_map_into_the_closed_set(engine_type: str | None, expected: str) -> None:
    assert value_types.value_type_for_engine_type(engine_type) == expected


@pytest.mark.parametrize(
    ("declared", "value"),
    [
        ("Sequence", ["/show/plate.0001.exr", "/show/plate.0002.exr"]),
        ("list[ImageUrlArtifact]", ["http://x/a.exr", "http://x/b.exr"]),
        ("list[int]", [1, 2, 3]),
        ("ImageUrlArtifact", "http://x/render.png"),
        ("VideoUrlArtifact", "/show/cut.mov"),
        ("bool", True),
        ("int", 7),
    ],
)
def test_declared_parameter_type_agrees_with_the_type_its_values_normalize_to(declared: str, value: Any) -> None:
    """A host builds a knob from the declared type and then receives values on it.

    The two disagreeing is worse than either being wrong alone: the plugin builds a text
    field for a parameter that goes on to stream image sequences. Sequence parameters are the case
    this library itself produces, so they are the case most likely to regress.
    """
    assert (
        value_types.value_type_for_engine_type(declared) == value_types.normalize_value(value, declared)["value_type"]
    )


@pytest.mark.parametrize(
    ("declared", "value", "runtime"),
    [
        ("GenericArtifact", GenericArtifact("https://cdn.example.com/still.jpg"), ValueType.IMAGE),
        ("GenericArtifact", GenericArtifact("https://cdn.example.com/notes.bin"), ValueType.FILE),
        ("AudioUrlArtifact", "https://cdn.example.com/take.mov", ValueType.MOVIE),
        ("ThreeDUrlArtifact", "/show/model.obj", ValueType.FILE),
    ],
)
def test_a_parameter_whose_declared_type_carries_no_media_information_may_narrow_at_runtime(
    declared: str, value: Any, runtime: str
) -> None:
    """An unmapped artifact class describes as GTFile, and its values may narrow to media.

    Nothing at describe time can know a GenericArtifact holds a jpg, because no value exists
    yet, and throwing that away once one does would be worse than the mismatch. So the
    narrowing is documented rather than removed, and pinned here: it must stay inside the
    sourced types and never become GTText, GTNumber or GTBool. That is the mismatch that
    actually breaks a host, because it makes it build a text field for media.
    """
    assert value_types.value_type_for_engine_type(declared) == ValueType.FILE
    assert value_types.normalize_value(value, declared)["value_type"] == runtime
    assert runtime in {ValueType.FILE, ValueType.IMAGE, ValueType.MOVIE}


@pytest.mark.parametrize(
    ("value", "declared", "expected"),
    [
        (ImageUrlArtifact(STATIC_URL), "ImageUrlArtifact", ValueType.IMAGE),
        (VideoUrlArtifact("http://x/plate.mov"), "VideoUrlArtifact", ValueType.MOVIE),
        (ImageArtifact(value=b"\x89PNG", format="png", width=4, height=2), "ImageArtifact", ValueType.IMAGE),
        ("/mnt/show/plate.exr", "str", ValueType.IMAGE),
        ("/mnt/show/plate.mov", "str", ValueType.MOVIE),
        ("/mnt/show/notes.txt", "str", ValueType.FILE),
        ("a hazy afternoon", "str", ValueType.TEXT),
        ("3/4 cup", "str", ValueType.TEXT),
        ("aspect 16/9", "str", ValueType.TEXT),
        (BlobArtifact(value=b"\x00\x01"), "BlobArtifact", ValueType.FILE),
        (None, "ImageUrlArtifact", ValueType.NULL),
        (True, "bool", ValueType.BOOL),
        (23.976, "float", ValueType.NUMBER),
        (7, "int", ValueType.NUMBER),
    ],
)
def test_values_normalize_into_the_closed_set(value: Any, declared: str, expected: str) -> None:
    descriptor = value_types.normalize_value(value, declared)
    assert descriptor["value_type"] == expected
    assert descriptor["value_type"] in VALUE_TYPES


def test_every_descriptor_reports_a_member_of_the_closed_set() -> None:
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
    assert value_types.normalize_value(True)["value_type"] == ValueType.BOOL
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
    """The parameter author knew the media type; the filename may not carry it."""
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
    assert value_types.normalize_value(STATIC_URL, "str")["sources"][0]["kind"] == SourceKind.URL
    assert value_types.normalize_value("/mnt/show/plate.exr", "str")["sources"][0]["kind"] == SourceKind.PATH
    inline = value_types.normalize_value(ImageArtifact(value=b"\x89PNG", format="png", width=1, height=1))
    assert inline["sources"][0]["kind"] == SourceKind.INLINE
    assert inline["sources"][0]["byte_count"] == 4


def test_a_literal_windows_path_is_slash_normalized_without_going_through_a_macro() -> None:
    descriptor = value_types.normalize_value("C:\\workspace\\outputs\\render.png", "str")
    source = descriptor["sources"][0]
    assert source["value"] == "C:/workspace/outputs/render.png"
    assert "\\" not in source["value"]


def test_a_frame_list_is_one_image_with_many_sources() -> None:
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
        ("renders/out.mov", "str", ValueType.MOVIE, True),
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
    descriptor = value_types.normalize_value(value, declared)
    assert descriptor["value_type"] == expected_type
    if expect_source:
        assert len(descriptor["sources"]) == 1
        assert descriptor["sources"][0]["value"] == value
    else:
        assert descriptor["sources"] == []


SOURCELESS_VALUE_TYPES = {ValueType.TEXT, ValueType.NUMBER, ValueType.BOOL, ValueType.NULL}


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
    """GTImage, GTMovie and GTFile promise a host somewhere to get bytes, so they must carry a source.

    Both docs publish the inverse rule too: only GTText, GTNumber, GTBool and GTNull arrive
    sourceless. A declared media type describes what a parameter is for, not what a value turned out
    to be, so prose on an image parameter must not be announced as an image a host can open.
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
    expected_top = {"value_type", "value", "sources", "colorspace", "engine_type"}
    expected_source = {"kind", "value", "format", "width", "height", "byte_count", "is_pattern", "raw"}
    for value in [None, "prose", "/a/b.exr", b"x", ImageUrlArtifact(STATIC_URL), 1, True]:
        descriptor = value_types.normalize_value(value)
        assert set(descriptor) == expected_top
        for source in descriptor["sources"]:
            assert set(source) == expected_source


class TestSerializedArtifacts:
    """A read hands back an artifact as a dict, where `getattr(value, "value")` finds nothing.

    The engine answers GetParameterValueRequest for an artifact-typed parameter with
    `{"type": "ImageUrlArtifact", "value": "..."}` rather than the artifact object, so a
    normalizer that only reaches for attributes reports an image output as sourceless text
    and the host has nothing to open.
    """

    SERIALIZED = {
        "type": "ImageUrlArtifact",
        "id": "5c8be9c5889b442689bb34db168ec903",
        "reference": None,
        "meta": {},
        "name": "5c8be9c5889b442689bb34db168ec903",
        "value": STATIC_URL,
    }

    def test_a_serialized_artifact_keeps_its_locator(self) -> None:
        descriptor = value_types.normalize_value(self.SERIALIZED, "ImageUrlArtifact")

        assert descriptor["value_type"] == ValueType.IMAGE
        assert [source["value"] for source in descriptor["sources"]] == [STATIC_URL]

    def test_the_dicts_own_type_is_reported(self) -> None:
        """`engine_type` is diagnostic, and "dict" tells support nothing about the value."""
        assert value_types.normalize_value(self.SERIALIZED)["engine_type"] == "ImageUrlArtifact"

    def test_a_serialized_sequence_carries_every_frame(self) -> None:
        frames = {
            "type": "ImageSequenceArtifact",
            "value": [f"/mnt/show/frame.{number:04d}.exr" for number in (1, 2, 3)],
        }

        descriptor = value_types.normalize_value(frames)

        assert descriptor["value_type"] == ValueType.IMAGE
        assert len(descriptor["sources"]) == 3

    def test_a_dict_that_is_not_an_artifact_stays_sourceless_text(self) -> None:
        descriptor = value_types.normalize_value({"width": 1920, "height": 1080})

        assert descriptor["value_type"] == ValueType.TEXT
        assert descriptor["sources"] == []

    def test_an_artifact_serialized_without_a_value_is_sourceless(self) -> None:
        descriptor = value_types.normalize_value({"type": "ImageUrlArtifact", "value": None})

        assert descriptor["sources"] == []
        assert descriptor["engine_type"] == "ImageUrlArtifact"


class TestScalarValues:
    """A scalar has no locator, so without this field a host cannot read it at all.

    Reading one back is also what keeps a host from having to remember what it last sent:
    `sources` answers for media, and this answers for everything else.
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (True, True),
            (False, False),
            (7, 7),
            (1.5, 1.5),
            ("[SUCCEEDED] no connection provided", "[SUCCEEDED] no connection provided"),
            ("", ""),
        ],
    )
    def test_a_scalar_is_carried(self, value: Any, expected: Any) -> None:
        assert value_types.normalize_value(value)["value"] == expected

    def test_unset_is_null(self) -> None:
        descriptor = value_types.normalize_value(None)
        assert descriptor["value_type"] == ValueType.NULL
        assert descriptor["value"] is None

    @pytest.mark.parametrize(
        "value",
        [
            STATIC_URL,
            "/mnt/show/plate.exr",
            ImageUrlArtifact(STATIC_URL),
            ImageArtifact(value=b"\x89PNG", format="png", width=1, height=1),
            ListArtifact([ImageUrlArtifact("http://x/a.png")]),
            {"type": "ImageUrlArtifact", "value": STATIC_URL},
        ],
    )
    def test_a_sourced_value_stays_null(self, value: Any) -> None:
        """The locator belongs in `sources`. Two places to look for one value is one too many."""
        descriptor = value_types.normalize_value(value)
        assert descriptor["sources"]
        assert descriptor["value"] is None

    def test_prose_declared_as_media_keeps_its_text(self) -> None:
        """Downgraded to GTText because it points at no bytes, and still readable as text."""
        descriptor = value_types.normalize_value("not a path at all", "ImageUrlArtifact")

        assert descriptor["value_type"] == ValueType.TEXT
        assert descriptor["value"] == "not a path at all"

    def test_an_unresolvable_macro_that_is_not_a_locator_keeps_its_template(self) -> None:
        """Prose with a brace token is text, and the text is the only thing a host can show."""
        descriptor = value_types.normalize_value("shot {SHOT} approved", "str")

        assert descriptor["value_type"] == ValueType.TEXT
        assert descriptor["value"] == "shot {SHOT} approved"
