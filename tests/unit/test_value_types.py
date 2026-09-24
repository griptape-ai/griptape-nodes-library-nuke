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
from griptape_nodes.common.sequences.models import MissingItemPolicy, Sequence, SequenceEntry
from griptape_nodes.retained_mode.events.event_converter import safe_unstructure
from griptape_nodes.retained_mode.events.project_events import (
    GetPathForMacroResultFailure,
    PathResolutionFailureReason,
)

from nuke_host_api import value_types
from nuke_host_api.protocol import VALUE_TYPES, ValueType
from nuke_host_api.value_types import UnrepresentableValueError

URL = "https://cdn.example.com/render.png"


@pytest.fixture(autouse=True)
def _unresolvable_macros(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse macro resolution instead of reaching the real engine, which unit tests must not boot."""

    class RefusingEngine:
        @staticmethod
        def handle_request(request: Any) -> Any:  # noqa: ARG004
            return GetPathForMacroResultFailure(
                failure_reason=PathResolutionFailureReason.MISSING_REQUIRED_VARIABLES,
                missing_variables={"frame"},
                result_details="missing required variables",
            )

    monkeypatch.setattr(value_types, "GriptapeNodes", RefusingEngine)


def _sequence(*paths: str) -> Sequence:
    return Sequence(
        entries=[
            SequenceEntry(number=number, padded_number=f"{number:04d}", path=path)
            for number, path in enumerate(paths, start=1001)
        ],
        first=1001,
        last=1000 + len(paths),
        discovered_first=1001,
        discovered_last=1000 + len(paths),
        padding=4,
        pattern="/show/plate/frame_####.png",
        directory="/show/plate",
        policy=MissingItemPolicy.SKIP,
    )


@pytest.mark.parametrize(
    ("engine_type", "expected"),
    [
        ("ImageArtifact", ValueType.IMAGE),
        ("ImageUrlArtifact", ValueType.IMAGE),
        ("VideoUrlArtifact", ValueType.MOVIE),
        ("VideoArtifact", ValueType.MOVIE),
        ("str", ValueType.TEXT),
        ("int", ValueType.INT),
        ("float", ValueType.FLOAT),
        ("bool", ValueType.BOOL),
        ("Sequence", ValueType.IMAGE),
        ("ImageSequenceArtifact", ValueType.IMAGE),
        ("list[ImageUrlArtifact]", ValueType.IMAGE),
        ("list[VideoUrlArtifact]", ValueType.MOVIE),
        ("list[int]", ValueType.INT),
        ("list[str]", ValueType.TEXT),
        ("list[AudioUrlArtifact]", ValueType.FILE),
        ("list", ValueType.TEXT),
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
    ("engine_type", "expected"),
    [
        ("list", True),
        ("list[ImageUrlArtifact]", True),
        ("list[int]", True),
        ("Sequence", True),
        ("ImageSequenceArtifact", True),
        ("ListArtifact", True),
        ("ImageUrlArtifact", False),
        ("str", False),
        ("int", False),
        ("any", None),
        ("Any", None),
        ("all", None),
        (None, None),
    ],
)
def test_list_cardinality_is_read_from_the_declared_type(engine_type: str | None, expected: bool | None) -> None:
    assert value_types.is_list_type(engine_type) is expected


@pytest.mark.parametrize(
    ("declared", "value"),
    [
        ("Sequence", _sequence("/show/plate/frame_1001.png", "/show/plate/frame_1002.png")),
        ("list[ImageUrlArtifact]", [ImageUrlArtifact("/x/a.exr"), ImageUrlArtifact("/x/b.exr")]),
        ("list[int]", [1, 2, 3]),
        ("ImageUrlArtifact", "/x/render.png"),
        ("VideoUrlArtifact", "/show/cut.mov"),
        ("bool", True),
        ("int", 7),
    ],
)
def test_declared_parameter_type_agrees_with_the_type_its_values_normalize_to(declared: str, value: Any) -> None:
    assert (
        value_types.value_type_for_engine_type(declared) == value_types.normalize_value(value, declared)["value_type"]
    )


@pytest.mark.parametrize(
    ("declared", "value", "runtime"),
    [
        ("GenericArtifact", GenericArtifact("/show/still.jpg"), ValueType.IMAGE),
        ("GenericArtifact", GenericArtifact("/show/notes.bin"), ValueType.FILE),
        ("AudioUrlArtifact", "/show/take.mov", ValueType.MOVIE),
        ("ThreeDUrlArtifact", "/show/model.obj", ValueType.FILE),
    ],
)
def test_a_parameter_whose_declared_type_carries_no_media_information_may_narrow_at_runtime(
    declared: str, value: Any, runtime: str
) -> None:
    """Narrowing stays inside the sourced types, so a host never gets a text field for media."""
    assert value_types.value_type_for_engine_type(declared) == ValueType.FILE
    assert value_types.normalize_value(value, declared)["value_type"] == runtime


@pytest.mark.parametrize(
    ("value", "declared", "expected"),
    [
        (ImageUrlArtifact("/show/render.png"), "ImageUrlArtifact", ValueType.IMAGE),
        (VideoUrlArtifact("/show/plate.mov"), "VideoUrlArtifact", ValueType.MOVIE),
        ("/mnt/show/plate.exr", "str", ValueType.IMAGE),
        ("/mnt/show/plate.mov", "str", ValueType.MOVIE),
        ("/mnt/show/notes.txt", "str", ValueType.FILE),
        ("a hazy afternoon", "str", ValueType.TEXT),
        ("3/4 cup", "str", ValueType.TEXT),
        (None, "ImageUrlArtifact", ValueType.IMAGE),
        (True, "bool", ValueType.BOOL),
        (23.976, "float", ValueType.FLOAT),
        (7, "int", ValueType.INT),
    ],
)
def test_values_normalize_into_the_closed_set(value: Any, declared: str, expected: str) -> None:
    descriptor = value_types.normalize_value(value, declared)
    assert descriptor["value_type"] == expected
    assert descriptor["value_type"] in VALUE_TYPES


def test_bool_is_not_reported_as_a_number() -> None:
    """bool is a subclass of int in Python, so order of checks matters."""
    assert value_types.normalize_value(True)["value_type"] == ValueType.BOOL
    assert value_types.normalize_value(1)["value_type"] == ValueType.INT


class TestNumericTypes:
    """Nuke builds a different knob for each, and truncating a float to an Int_Knob loses the value."""

    @pytest.mark.parametrize(
        ("value", "declared", "expected"),
        [
            (7, "int", ValueType.INT),
            (7, None, ValueType.INT),
            (23.976, "float", ValueType.FLOAT),
            (23.976, None, ValueType.FLOAT),
            # Preserve a Double_Knob for later fractional values.
            (4, "float", ValueType.FLOAT),
            # Do not truncate a runtime float to match its int declaration.
            (0.5, "int", ValueType.FLOAT),
        ],
    )
    def test_a_number_is_typed_from_its_value_and_its_declaration(
        self, value: Any, declared: str | None, expected: str
    ) -> None:
        assert value_types.normalize_value(value, declared)["value_type"] == expected

    def test_a_list_of_ints_and_floats_is_one_float_rather_than_a_conflict(self) -> None:
        descriptor = value_types.normalize_value([1, 2.5], "list[int]")
        assert descriptor["value_type"] == ValueType.FLOAT
        assert descriptor["value"] == [1, 2.5]


class TestDescriptorShape:
    def test_a_descriptor_has_exactly_three_fields(self) -> None:
        for value in [None, "prose", "/a/b.exr", ImageUrlArtifact("/a/b.png"), 1, True, [1, 2]]:
            assert set(value_types.normalize_value(value)) == {"value_type", "value", "engine_type"}

    def test_a_media_entry_carries_path_and_format(self) -> None:
        descriptor = value_types.normalize_value("/mnt/show/plate.exr", "ImageUrlArtifact")
        assert descriptor["value"] == {"path": "/mnt/show/plate.exr", "format": "exr"}

    def test_engine_type_is_carried_for_diagnostics(self) -> None:
        descriptor = value_types.normalize_value(ImageUrlArtifact("/a/b.png"), "ImageUrlArtifact")
        assert descriptor["engine_type"] == "ImageUrlArtifact"

    @pytest.mark.parametrize("declared", ["str", "ImageUrlArtifact", "VideoUrlArtifact", "GenericArtifact", None])
    @pytest.mark.parametrize(
        "value", ["just prose", "3/4 cup", "shots/plate", "/mnt/show/plate.exr", "shots/plate.exr", 7, True]
    )
    def test_a_media_or_file_type_always_carries_a_path(self, value: Any, declared: str | None) -> None:
        """GTImage, GTMovie and GTFile promise a host a file to open."""
        descriptor = value_types.normalize_value(value, declared)
        if descriptor["value_type"] in {ValueType.IMAGE, ValueType.MOVIE, ValueType.FILE}:
            assert isinstance(descriptor["value"], dict)
            assert descriptor["value"]["path"]
        else:
            assert not isinstance(descriptor["value"], dict)


class TestCardinality:
    def test_a_single_parameter_carries_one_value(self) -> None:
        assert value_types.normalize_value("a quiet harbour", "str")["value"] == "a quiet harbour"

    def test_a_list_parameter_carries_an_array_even_for_one_item(self) -> None:
        descriptor = value_types.normalize_value([ImageUrlArtifact("/a/one.png")], "list[ImageUrlArtifact]")
        assert descriptor["value"] == [{"path": "/a/one.png", "format": "png"}]

    def test_a_single_value_on_a_list_parameter_is_wrapped(self) -> None:
        descriptor = value_types.normalize_value(ImageUrlArtifact("/a/one.png"), "list[ImageUrlArtifact]")
        assert descriptor["value"] == [{"path": "/a/one.png", "format": "png"}]

    @pytest.mark.parametrize("unset", [None, ""])
    def test_an_unset_list_parameter_is_an_empty_array(self, unset: Any) -> None:
        descriptor = value_types.normalize_value(unset, "list[ImageUrlArtifact]")
        assert descriptor == {"value_type": ValueType.IMAGE, "value": [], "engine_type": type(unset).__name__}

    @pytest.mark.parametrize("unset", [None, "", {"type": "ImageUrlArtifact", "value": None}])
    def test_an_unset_single_media_parameter_is_null_with_its_declared_type(self, unset: Any) -> None:
        descriptor = value_types.normalize_value(unset, "ImageUrlArtifact")
        assert descriptor["value_type"] == ValueType.IMAGE
        assert descriptor["value"] is None

    def test_a_list_of_scalars_keeps_every_value(self) -> None:
        assert value_types.normalize_value([42, 43], "list[int]")["value"] == [42, 43]
        assert value_types.normalize_value(["sh010", "sh020"], "list[str]")["value"] == ["sh010", "sh020"]

    def test_a_list_on_a_single_parameter_is_unrepresentable(self) -> None:
        with pytest.raises(UnrepresentableValueError, match="single value"):
            value_types.normalize_value(["/a/one.png", "/a/two.png"], "ImageUrlArtifact")

    def test_a_wildcard_takes_its_shape_from_the_value(self) -> None:
        assert value_types.normalize_value("/a/one.png", "any")["value"] == {"path": "/a/one.png", "format": "png"}
        assert value_types.normalize_value(["/a/one.png"], "any")["value"] == [{"path": "/a/one.png", "format": "png"}]

    def test_a_nested_list_is_unrepresentable(self) -> None:
        with pytest.raises(UnrepresentableValueError, match="nested"):
            value_types.normalize_value([[1, 2], [3]], "list[int]")


class TestLists:
    def test_a_list_artifact_carries_every_frame(self) -> None:
        frames = ListArtifact([ImageUrlArtifact(f"/x/frame.{n:04d}.exr") for n in (1, 2, 3)])
        descriptor = value_types.normalize_value(frames, "ListArtifact")
        assert descriptor["value_type"] == ValueType.IMAGE
        assert [entry["path"] for entry in descriptor["value"]] == [f"/x/frame.{n:04d}.exr" for n in (1, 2, 3)]

    @pytest.mark.parametrize("serialize", [False, True])
    def test_a_sequence_carries_every_frame(self, serialize: bool) -> None:
        sequence = _sequence("/show/plate/frame_1001.png", "/show/plate/frame_1002.png")
        value = safe_unstructure(sequence) if serialize else sequence

        descriptor = value_types.normalize_value(value, "Sequence")

        assert descriptor["value_type"] == ValueType.IMAGE
        assert descriptor["value"] == [
            {"path": "/show/plate/frame_1001.png", "format": "png"},
            {"path": "/show/plate/frame_1002.png", "format": "png"},
        ]

    def test_a_list_of_images_and_movies_degrades_to_files(self) -> None:
        mixed = [ImageUrlArtifact("/x/a.png"), VideoUrlArtifact("/x/b.mov")]
        assert value_types.normalize_value(mixed, "list")["value_type"] == ValueType.FILE

    def test_a_list_mixing_text_and_media_is_unrepresentable(self) -> None:
        with pytest.raises(UnrepresentableValueError, match="mixes"):
            value_types.normalize_value(["a cat", "/x/a.png"], "list[str]")

    def test_an_empty_list_takes_the_declared_element_type(self) -> None:
        assert value_types.normalize_value([], "list[VideoUrlArtifact]") == {
            "value_type": ValueType.MOVIE,
            "value": [],
            "engine_type": "list",
        }


class TestLocators:
    def test_declared_type_outranks_the_extension(self) -> None:
        """The parameter author knew the media type; the filename may not carry it."""
        descriptor = value_types.normalize_value("/mnt/show/no_extension", "ImageUrlArtifact")
        assert descriptor["value_type"] == ValueType.IMAGE
        assert descriptor["value"]["format"] is None

    def test_unknown_artifact_class_is_classified_by_extension(self) -> None:
        descriptor = value_types.normalize_value(GenericArtifact("/show/still.jpg"))
        assert descriptor["value_type"] == ValueType.IMAGE
        assert descriptor["value"]["format"] == "jpg"

    @pytest.mark.parametrize(
        "extension",
        ["mp4", "mov", "avi", "mkv", "webm", "m4v", "mpg", "mpeg", "m2v", "wmv", "ogv", "mts", "m2ts", "r3d"],
    )
    def test_a_movie_container_nuke_reads_is_a_movie(self, extension: str) -> None:
        assert value_types.normalize_value(f"/show/cut.{extension}", "str")["value_type"] == ValueType.MOVIE

    def test_an_ambiguous_container_stays_a_file_until_a_declared_type_says_otherwise(self) -> None:
        """MXF wraps audio-only essence too, so the extension alone cannot promise a movie."""
        assert value_types.normalize_value("/show/master.mxf", "str")["value_type"] == ValueType.FILE
        assert value_types.normalize_value("/show/master.mxf", "VideoArtifact")["value_type"] == ValueType.MOVIE

    def test_a_literal_windows_path_is_slash_normalized(self) -> None:
        descriptor = value_types.normalize_value("C:\\workspace\\outputs\\render.png", "str")
        assert descriptor["value"]["path"] == "C:/workspace/outputs/render.png"

    @pytest.mark.parametrize(
        ("value", "expected_type", "expect_path"),
        [
            ("/mnt/show/plate.exr", ValueType.IMAGE, True),
            ("/mnt/show/notes.txt", ValueType.FILE, True),
            ("/mnt/show/renders", ValueType.FILE, True),
            # A relative path is the ordinary form in a Nuke script.
            ("shots/plate.exr", ValueType.IMAGE, True),
            ("renders/out.mov", ValueType.MOVIE, True),
            ("notes/readme.txt", ValueType.FILE, True),
            # Prose that merely contains a slash stays prose.
            ("3/4 cup", ValueType.TEXT, False),
            ("aspect 16/9", ValueType.TEXT, False),
            ("shots/plate", ValueType.TEXT, False),
            # This protocol version has no URL concept, so a URL on a text parameter is text.
            (URL, ValueType.TEXT, False),
        ],
    )
    def test_locator_fallback_matrix_on_a_text_parameter(
        self, value: str, expected_type: str, expect_path: bool
    ) -> None:
        descriptor = value_types.normalize_value(value, "str")
        assert descriptor["value_type"] == expected_type
        if expect_path:
            assert descriptor["value"]["path"] == value
        else:
            assert descriptor["value"] == value

    def test_prose_declared_as_media_is_text(self) -> None:
        descriptor = value_types.normalize_value("not a path at all", "ImageUrlArtifact")
        assert descriptor == {"value_type": ValueType.TEXT, "value": "not a path at all", "engine_type": "str"}


class TestUnrepresentable:
    @pytest.mark.parametrize("value", [URL, ImageUrlArtifact(URL), {"type": "ImageUrlArtifact", "value": URL}])
    def test_a_url_on_a_media_parameter(self, value: Any) -> None:
        with pytest.raises(UnrepresentableValueError, match="URL"):
            value_types.normalize_value(value, "ImageUrlArtifact")

    @pytest.mark.parametrize(
        "value",
        [
            ImageArtifact(value=b"\x89PNG", format="png", width=4, height=2),
            safe_unstructure(ImageArtifact(value=b"\x89PNG", format="png", width=4, height=2)),
            BlobArtifact(value=b"\x00\x01"),
            b"raw",
        ],
    )
    def test_bytes_the_engine_never_saved(self, value: Any) -> None:
        with pytest.raises(UnrepresentableValueError, match="bytes"):
            value_types.normalize_value(value, "ImageUrlArtifact")

    def test_a_dict_that_is_not_an_artifact(self) -> None:
        with pytest.raises(UnrepresentableValueError, match="dict"):
            value_types.normalize_value({"width": 1920, "height": 1080}, "dict")


class TestSerializedArtifacts:
    """A read hands back an artifact as a dict rather than the artifact object."""

    SERIALIZED = {
        "type": "ImageUrlArtifact",
        "id": "5c8be9c5889b442689bb34db168ec903",
        "reference": None,
        "meta": {},
        "name": "5c8be9c5889b442689bb34db168ec903",
        "value": "/show/render.png",
    }

    def test_a_serialized_artifact_keeps_its_path(self) -> None:
        descriptor = value_types.normalize_value(self.SERIALIZED, "ImageUrlArtifact")
        assert descriptor["value"] == {"path": "/show/render.png", "format": "png"}

    def test_the_dicts_own_type_is_reported(self) -> None:
        assert value_types.normalize_value(self.SERIALIZED)["engine_type"] == "ImageUrlArtifact"

    def test_a_serialized_image_sequence_carries_every_frame(self) -> None:
        frames = {"type": "ImageSequenceArtifact", "value": [f"/show/frame.{n:04d}.exr" for n in (1, 2, 3)]}
        descriptor = value_types.normalize_value(frames, "ImageSequenceArtifact")
        assert descriptor["value_type"] == ValueType.IMAGE
        assert len(descriptor["value"]) == 3


class TestEngineValue:
    """A host sends back what it read, and the engine is handed what it holds."""

    def test_a_media_entry_becomes_its_path(self) -> None:
        assert value_types.engine_value({"path": "/a/b.png", "format": "png"}) == "/a/b.png"

    def test_a_list_of_entries_becomes_a_list_of_paths(self) -> None:
        entries = [{"path": "/a/1.png", "format": "png"}, {"path": "/a/2.png", "format": None}]
        assert value_types.engine_value(entries) == ["/a/1.png", "/a/2.png"]

    @pytest.mark.parametrize("value", ["prose", 7, True, None, [1, 2], {"path": "/a", "other": 1}])
    def test_anything_else_passes_through(self, value: Any) -> None:
        assert value_types.engine_value(value) == value

    def test_a_read_value_round_trips(self) -> None:
        read = value_types.normalize_value([ImageUrlArtifact("/a/1.png")], "list[ImageUrlArtifact]")["value"]
        assert value_types.engine_value(read) == ["/a/1.png"]
