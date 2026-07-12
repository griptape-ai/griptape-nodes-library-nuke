"""Unit tests for NukeScriptNode — pure logic only, no Nuke process spawned."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from griptape_nodes.retained_mode.events.os_events import (
    DeleteFileRequest,
    WriteFileRequest,
    WriteFileResultFailure,
    WriteFileResultSuccess,
)

from nuke_nodes.nuke_script_node import _coerce_knob_value, _path_to_artifact

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Module-level pure functions
# ---------------------------------------------------------------------------


def _mock_project_file_destination(
    location: str = "http://static/file", resolved_path: str = "/fake/temp/placeholder.png"
) -> MagicMock:
    mock_saved = MagicMock()
    mock_saved.location = location
    mock_dest_instance = MagicMock()
    mock_dest_instance.write_bytes.return_value = mock_saved
    mock_dest_instance.resolve.return_value = resolved_path
    mock_dest_cls = MagicMock()
    mock_dest_cls.from_situation.return_value = mock_dest_instance
    return mock_dest_cls


class TestPathToArtifact:
    def test_video_url_artifact_returns_video_url_artifact(self, tmp_path: Path) -> None:
        video_file = tmp_path / "clip.mp4"
        video_file.write_bytes(b"\x00" * 16)

        mock_dest_cls = _mock_project_file_destination("http://static/clip.mp4")
        mock_file = MagicMock()
        mock_file.read_bytes.return_value = b"\x00" * 16

        with (
            patch("nuke_nodes.nuke_script_node.File", return_value=mock_file),
            patch("nuke_nodes.nuke_script_node.ProjectFileDestination", mock_dest_cls),
        ):
            result = _path_to_artifact("VideoUrlArtifact", str(video_file))

        from griptape.artifacts import VideoUrlArtifact

        assert isinstance(result, VideoUrlArtifact)
        assert result.value == "http://static/clip.mp4"

    def test_image_sequence_artifact_returns_list_artifact(self, tmp_path: Path) -> None:
        f1 = tmp_path / "frame.0001.png"
        f2 = tmp_path / "frame.0002.png"
        f1.write_bytes(b"\x89PNG")
        f2.write_bytes(b"\x89PNG")

        saved1, saved2 = MagicMock(), MagicMock()
        saved1.location = "http://s/f1.png"
        saved2.location = "http://s/f2.png"
        dest1, dest2 = MagicMock(), MagicMock()
        dest1.write_bytes.return_value = saved1
        dest2.write_bytes.return_value = saved2
        mock_dest_cls = MagicMock()
        mock_dest_cls.from_situation.side_effect = [dest1, dest2]

        mock_file = MagicMock()
        mock_file.read_bytes.return_value = b"\x89PNG"

        with (
            patch("nuke_nodes.nuke_script_node.File", return_value=mock_file),
            patch("nuke_nodes.nuke_script_node.ProjectFileDestination", mock_dest_cls),
        ):
            result = _path_to_artifact("ImageSequenceArtifact", [str(f1), str(f2)])

        from griptape.artifacts import ImageUrlArtifact, ListArtifact

        assert isinstance(result, ListArtifact)
        assert len(result.value) == 2
        assert all(isinstance(item, ImageUrlArtifact) for item in result.value)

    def test_image_sequence_artifact_empty_list_returns_empty_list_artifact(self) -> None:
        with patch("nuke_nodes.nuke_script_node.GriptapeNodes"):
            result = _path_to_artifact("ImageSequenceArtifact", [])

        from griptape.artifacts import ListArtifact

        assert isinstance(result, ListArtifact)
        assert len(result.value) == 0

    def test_image_sequence_artifact_raises_type_error_for_str_path(self) -> None:
        with pytest.raises(TypeError, match="ImageSequenceArtifact"):
            _path_to_artifact("ImageSequenceArtifact", "/tmp/frame.%04d.png")

    def test_image_artifact_unchanged(self, tmp_path: Path) -> None:
        img_file = tmp_path / "out.png"
        img_file.write_bytes(b"\x89PNG")

        mock_dest_cls = _mock_project_file_destination("http://static/out.png")
        mock_file = MagicMock()
        mock_file.read_bytes.return_value = b"\x89PNG"

        with (
            patch("nuke_nodes.nuke_script_node.File", return_value=mock_file),
            patch("nuke_nodes.nuke_script_node.ProjectFileDestination", mock_dest_cls),
        ):
            result = _path_to_artifact("ImageArtifact", str(img_file))

        from griptape.artifacts import ImageUrlArtifact

        assert isinstance(result, ImageUrlArtifact)


def _mock_artifact_to_path_dest(resolved_path: str = "/fake/temp/input.mp4") -> MagicMock:
    dest = MagicMock()
    dest.resolve.return_value = resolved_path
    mock_cls = MagicMock()
    mock_cls.from_situation.return_value = dest
    return mock_cls


class TestArtifactToPath:
    def test_video_url_artifact_http_downloads_to_project_temp(self) -> None:
        node = _make_node()

        try:
            from griptape.artifacts import VideoUrlArtifact

            artifact = VideoUrlArtifact(value="http://example.com/clip.mp4")
        except ImportError:
            pytest.skip("griptape not installed")

        fake_response = MagicMock()
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)
        fake_response.read.return_value = b"\x00" * 8

        mock_dest_cls = _mock_artifact_to_path_dest("/fake/temp/input_resolve.mp4")
        canonical_path = "/fake/temp/input_canonical.mp4"

        with (
            patch("nuke_nodes.nuke_script_node.urllib.request.urlopen", return_value=fake_response) as mock_open,
            patch("nuke_nodes.nuke_script_node.ProjectFileDestination", mock_dest_cls),
            patch("nuke_nodes.nuke_script_node.GriptapeNodes") as mock_gtn,
        ):
            write_result = MagicMock(spec=WriteFileResultSuccess)
            write_result.final_file_path = canonical_path
            mock_gtn.handle_request.return_value = write_result
            result = node._artifact_to_path(artifact, name="my_input")

        mock_open.assert_called_once()
        assert result == canonical_path
        call_args = mock_dest_cls.from_situation.call_args
        filename, situation = call_args[0]
        assert situation == "save_temp_file"
        assert "NukeScriptNode1" in filename
        assert "my_input" in filename
        assert filename.endswith(".mp4")

    def test_video_url_artifact_http_appends_to_cleanup_list(self) -> None:
        node = _make_node()

        try:
            from griptape.artifacts import VideoUrlArtifact

            artifact = VideoUrlArtifact(value="http://example.com/clip.mp4")
        except ImportError:
            pytest.skip("griptape not installed")

        fake_response = MagicMock()
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)
        fake_response.read.return_value = b"\x00" * 8

        cleanup: list[str] = []
        mock_dest_cls = _mock_artifact_to_path_dest("/fake/temp/input_resolve.mp4")
        canonical_path = "/fake/temp/input_canonical.mp4"

        with (
            patch("nuke_nodes.nuke_script_node.urllib.request.urlopen", return_value=fake_response),
            patch("nuke_nodes.nuke_script_node.ProjectFileDestination", mock_dest_cls),
            patch("nuke_nodes.nuke_script_node.GriptapeNodes") as mock_gtn,
        ):
            write_result = MagicMock(spec=WriteFileResultSuccess)
            write_result.final_file_path = canonical_path
            mock_gtn.handle_request.return_value = write_result
            node._artifact_to_path(artifact, name="my_input", _cleanup=cleanup)

        assert cleanup == [canonical_path]

    def test_bytes_artifact_writes_to_project_temp_file(self) -> None:
        node = _make_node()

        class FakeArtifact:
            value = b"\x89PNG\x00"

        mock_dest_cls = _mock_artifact_to_path_dest("/fake/temp/input_resolve.png")
        canonical_path = "/fake/temp/input_canonical.png"
        cleanup: list[str] = []

        with (
            patch("nuke_nodes.nuke_script_node.ProjectFileDestination", mock_dest_cls),
            patch("nuke_nodes.nuke_script_node.GriptapeNodes") as mock_gtn,
        ):
            write_result = MagicMock(spec=WriteFileResultSuccess)
            write_result.final_file_path = canonical_path
            mock_gtn.handle_request.return_value = write_result
            result = node._artifact_to_path(FakeArtifact(), name="img_in", _cleanup=cleanup)

        assert result == canonical_path
        call_args = mock_dest_cls.from_situation.call_args
        filename, situation = call_args[0]
        assert situation == "save_temp_file"
        assert "NukeScriptNode1" in filename
        assert "img_in" in filename
        assert filename.endswith(".png")
        assert cleanup == [canonical_path]

    def test_bytes_artifact_raises_on_write_failure(self) -> None:
        node = _make_node()

        class FakeArtifact:
            value = b"\x89PNG\x00"

        mock_dest_cls = _mock_artifact_to_path_dest("/fake/temp/input.png")
        mock_failure = MagicMock(spec=WriteFileResultFailure)

        with (
            patch("nuke_nodes.nuke_script_node.ProjectFileDestination", mock_dest_cls),
            patch("nuke_nodes.nuke_script_node.GriptapeNodes") as mock_gtn,
        ):
            mock_gtn.handle_request.return_value = mock_failure
            with pytest.raises(RuntimeError, match="scratch file"):
                node._artifact_to_path(FakeArtifact(), name="img_in")

    def test_video_url_artifact_local_path_returned_unchanged(self) -> None:
        node = _make_node()

        try:
            from griptape.artifacts import VideoUrlArtifact

            artifact = VideoUrlArtifact(value="/local/clip.mp4")
        except ImportError:
            pytest.skip("griptape not installed")

        result = node._artifact_to_path(artifact)
        assert result == "/local/clip.mp4"


class TestCoerceKnobValue:
    def test_integer_string(self) -> None:
        assert _coerce_knob_value("42") == 42
        assert isinstance(_coerce_knob_value("42"), int)

    def test_float_string(self) -> None:
        assert _coerce_knob_value("3.14") == pytest.approx(3.14)
        assert isinstance(_coerce_knob_value("3.14"), float)

    def test_plain_string(self) -> None:
        assert _coerce_knob_value("hello") == "hello"
        assert isinstance(_coerce_knob_value("hello"), str)

    def test_negative_int(self) -> None:
        assert _coerce_knob_value("-5") == -5

    def test_scientific_notation(self) -> None:
        result = _coerce_knob_value("1e3")
        assert result == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# NukeScriptNode class — tested via a lightweight mock of the framework base
# ---------------------------------------------------------------------------


def _make_node() -> Any:
    """Instantiate NukeScriptNode with the Griptape framework base mocked out."""
    with patch("nuke_nodes.nuke_script_node.SuccessFailureNode.__init__", return_value=None):
        from nuke_nodes.nuke_script_node import NukeScriptNode

        # Create a per-call subclass so the `parameters` property (which requires
        # root_ui_element from a fully-initialised base) can be safely stubbed.
        _Stub = type("_NukeScriptNodeStub", (NukeScriptNode,), {"parameters": property(lambda self: [])})
        node = _Stub.__new__(_Stub)
        # Replicate what __init__ sets on the instance
        node._dynamic_param_names = []
        node._dynamic_group_names = []
        node._annotations = []
        node._expose_knobs = []
        node._parsed_nodes = []
        node.metadata = {}
        node.parameter_output_values = MagicMock()  # type: ignore[assignment]
        node.name = "NukeScriptNode1"

        # Stub framework methods used by our code
        node.add_parameter = MagicMock()
        node.add_node_element = MagicMock()
        node.remove_parameter_element_by_name = MagicMock()
        node.get_parameter_value = MagicMock(return_value=None)
        node._clear_execution_status = MagicMock()
        node._set_status_results = MagicMock()
        node._handle_failure_exception = MagicMock()
        node._create_status_parameters = MagicMock()

        return node


class TestRefreshDynamicPorts:
    def test_clears_old_ports_on_missing_file(self, tmp_path: Path) -> None:
        node = _make_node()
        node._dynamic_param_names = ["old_param"]
        node._refresh_dynamic_ports(str(tmp_path / "nonexistent.nk"))
        node.remove_parameter_element_by_name.assert_called_once_with("old_param")
        assert node._dynamic_param_names == []

    def test_reads_sidecar_and_adds_ports(self, tmp_path: Path) -> None:
        # Use the real annotated fixture
        nk_fixture = FIXTURES / "constant_write.nk"
        if not nk_fixture.exists():
            pytest.skip("constant_write.nk fixture not present")

        node = _make_node()
        node._refresh_dynamic_ports(str(nk_fixture))

        # At least one parameter added for each annotation
        assert node.add_parameter.called

    def test_no_ports_added_for_unannotated_script(self, tmp_path: Path) -> None:
        nk_fixture = FIXTURES / "no_annotations.nk"
        if not nk_fixture.exists():
            pytest.skip("no_annotations.nk fixture not present")

        node = _make_node()
        node._refresh_dynamic_ports(str(nk_fixture))
        # No dynamic ports should be registered
        assert node._dynamic_param_names == []

    def test_input_ports_use_annotation_types(self, tmp_path: Path) -> None:
        from script_parser.annotation import GriptapeAnnotation

        nk_file = tmp_path / "typed_inputs.nk"
        nk_file.write_text("")
        sidecar_file = tmp_path / "typed_inputs.gt.json"
        sidecar_file.write_text("{}")
        annotations = [
            GriptapeAnnotation(node_name="Read1", role="input", gt_name="image", gt_type="ImageArtifact"),
            GriptapeAnnotation(node_name="ReadGeo1", role="input", gt_name="mesh", gt_type="ThreeDUrlArtifact"),
            GriptapeAnnotation(node_name="ReadVideo1", role="input", gt_name="clip", gt_type="VideoUrlArtifact"),
            GriptapeAnnotation(node_name="Text1", role="input", gt_name="label", gt_type="str"),
        ]

        node = _make_node()
        with patch("nuke_nodes.nuke_script_node.read_sidecar", return_value=(annotations, [], False)):
            node._refresh_dynamic_ports(str(nk_file))

        created_params = {call.args[0].name: call.args[0] for call in node.add_parameter.call_args_list}
        assert created_params["image"].input_types == ["str", "ImageArtifact", "ImageUrlArtifact", "BlobArtifact"]
        assert created_params["mesh"].input_types == ["ThreeDUrlArtifact"]
        assert created_params["clip"].input_types == ["str", "VideoUrlArtifact"]
        assert created_params["label"].input_types == ["str"]


class TestEnsureAnnotations:
    def test_noop_when_annotations_already_loaded(self) -> None:
        from script_parser.annotation import GriptapeAnnotation

        node = _make_node()
        node._annotations = [
            GriptapeAnnotation(node_name="Read1", role="input", gt_name="src", gt_type="ImageArtifact")
        ]
        node.get_parameter_value = MagicMock(return_value="/some/path.nk")
        node._ensure_annotations()
        # get_parameter_value should not be called because we returned early
        node.get_parameter_value.assert_not_called()

    def test_noop_when_no_script_path(self) -> None:
        node = _make_node()
        node.get_parameter_value = MagicMock(return_value=None)
        node._ensure_annotations()
        assert node._annotations == []


class TestInitMetadataGroupPreCreation:
    def test_pre_creates_groups_from_metadata(self) -> None:
        from nuke_nodes.nuke_script_node import NukeScriptNode

        metadata: dict = {"_nuke_dynamic_groups": ["Outputs", "GradeRed"]}

        node = NukeScriptNode.__new__(NukeScriptNode)
        node.remove_node_element = MagicMock()
        node._create_status_parameters = MagicMock()

        # Track interleaved call order across add_parameter and add_node_element.
        call_sequence: list[tuple[str, Any]] = []
        node.add_parameter = MagicMock(side_effect=lambda p: call_sequence.append(("param", p)))
        node.add_node_element = MagicMock(side_effect=lambda g: call_sequence.append(("group", g)))

        # super().__init__() is called bound, so side_effect receives (name, meta) — no self.
        # Use a closure to set metadata on the pre-created node instance.
        def fake_super_init(name: str, meta: dict | None = None) -> None:
            node.metadata = meta or {}

        with (
            patch("nuke_nodes.nuke_script_node.SuccessFailureNode.__init__", side_effect=fake_super_init),
            patch("nuke_nodes.nuke_script_node.GriptapeNodes"),
            patch("nuke_nodes.nuke_script_node.merged_installations", return_value=[]),
        ):
            node.__init__("TestNode", metadata)

        assert "Outputs" in node._dynamic_group_names
        assert "GradeRed" in node._dynamic_group_names

        # Dynamic groups must appear AFTER all static add_parameter calls in the
        # interleaved call sequence so the node UI shows static params first.
        last_static_param_pos = max(i for i, (kind, _) in enumerate(call_sequence) if kind == "param")
        first_dynamic_group_pos = min(
            i
            for i, (kind, obj) in enumerate(call_sequence)
            if kind == "group" and hasattr(obj, "name") and obj.name in {"Outputs", "GradeRed"}
        )
        assert last_static_param_pos < first_dynamic_group_pos, (
            "dynamic groups were added before static params — ordering is wrong"
        )


class TestRefreshDynamicPortsMetadata:
    def test_persists_group_names_to_metadata(self, tmp_path: Path) -> None:
        node = _make_node()
        node.metadata = {}
        nk_file = tmp_path / "test.nk"
        nk_file.write_text("")
        node._refresh_dynamic_ports(str(nk_file))
        assert "_nuke_dynamic_groups" in node.metadata
        assert isinstance(node.metadata["_nuke_dynamic_groups"], list)

    def test_float_exposed_knob_gets_slider_trait(self, tmp_path: Path) -> None:
        from griptape_nodes.traits.slider import Slider

        from script_parser.annotation import ExposedKnob

        nk_file = tmp_path / "grade.nk"
        nk_file.write_text("")

        ek = ExposedKnob(
            source_node="Grade1",
            knob_ref="Grade1.multiply",
            target_node="Grade1",
            target_knob="multiply",
            param_name="Grade1_multiply",
            knob_type="AColor_Knob",
        )

        node = _make_node()
        node.metadata = {}

        # Sidecar file must exist for the os.path.exists guard to pass.
        sidecar_file = tmp_path / "grade.gt.json"
        sidecar_file.write_text("{}")

        # read_sidecar returns (annotations, expose_knobs, is_stale).
        with patch("nuke_nodes.nuke_script_node.read_sidecar", return_value=([], [ek], False)):
            node._refresh_dynamic_ports(str(nk_file))

        # Capture the Parameter passed to add_parameter for Grade1_multiply
        created_params = {call.args[0].name: call.args[0] for call in node.add_parameter.call_args_list}
        assert "Grade1_multiply" in created_params
        param = created_params["Grade1_multiply"]
        from griptape_nodes.exe_types.core_types import Trait

        traits = param.find_elements_by_type(Trait)
        assert any(isinstance(t, Slider) for t in traits), "float param should have Slider trait"


class TestAfterValueSet:
    def test_always_calls_refresh_on_script_path(self) -> None:
        node = _make_node()
        node._refresh_dynamic_ports = MagicMock()
        mock_param = MagicMock()
        mock_param.name = "script_path"
        node.after_value_set(mock_param, "/some/script.nk")
        node._refresh_dynamic_ports.assert_called_once_with("/some/script.nk")

    def test_does_not_call_refresh_for_other_params(self) -> None:
        node = _make_node()
        node._refresh_dynamic_ports = MagicMock()
        mock_param = MagicMock()
        mock_param.name = "frame_start"
        node.after_value_set(mock_param, 1001)
        node._refresh_dynamic_ports.assert_not_called()


class TestProcess:
    def test_sets_success_status_on_zero_return_code(self, tmp_path: Path) -> None:
        from execution.provider import JobResult, JobStatus
        from script_parser.annotation import GriptapeAnnotation

        nk_file = tmp_path / "test.nk"
        nk_file.write_text("")

        node = _make_node()
        node._annotations = [
            GriptapeAnnotation(node_name="Write1", role="output", gt_name="result", gt_type="ImageArtifact")
        ]
        node._expose_knobs = []

        node.get_parameter_value = MagicMock(
            side_effect=lambda name: {
                "script_path": str(nk_file),
                "nuke_executable": "/usr/bin/nuke",
                "frame_start": 1001,
                "frame_end": 1001,
            }.get(name)
        )

        out_file = tmp_path / "out.png"
        out_file.write_bytes(b"")
        fake_result = JobResult(
            handle="handle-123",
            status=JobStatus.SUCCEEDED,
            return_code=0,
            log=[],
            outputs={"result": str(out_file)},
        )

        mock_dest_cls = _mock_project_file_destination("http://static/out.png")
        mock_file = MagicMock()
        mock_file.read_bytes.return_value = b"\x89PNG"

        with (
            patch("nuke_nodes.nuke_script_node.DirectSubprocessProvider") as MockProvider,
            patch("nuke_nodes.nuke_script_node.GriptapeNodes") as MockGT,
            patch("nuke_nodes.nuke_script_node.File", return_value=mock_file),
            patch("nuke_nodes.nuke_script_node.ProjectFileDestination", mock_dest_cls),
        ):
            MockGT.ConfigManager.return_value.get_config_value.return_value = None
            write_result = MagicMock(spec=WriteFileResultSuccess)
            write_result.final_file_path = "/fake/temp/placeholder.png"
            MockGT.handle_request.return_value = write_result
            instance = MockProvider.return_value
            instance.submit.return_value = "handle-123"
            instance.result.return_value = fake_result

            node.process()

        node._set_status_results.assert_called_once_with(was_successful=True, result_details="Render complete.")
        node._handle_failure_exception.assert_not_called()

    def test_routes_to_failure_on_nonzero_return_code(self, tmp_path: Path) -> None:
        from execution.provider import JobResult, JobStatus

        nk_file = tmp_path / "test.nk"
        nk_file.write_text("")

        node = _make_node()
        node._annotations = []
        node._expose_knobs = []

        node.get_parameter_value = MagicMock(
            side_effect=lambda name: {
                "script_path": str(nk_file),
                "nuke_executable": "/usr/bin/nuke",
                "frame_start": 1001,
                "frame_end": 1001,
            }.get(name)
        )

        fake_result = JobResult(
            handle="handle-456",
            status=JobStatus.FAILED,
            return_code=1,
            log=["Error: missing licence"],
            outputs={},
        )

        with (
            patch("nuke_nodes.nuke_script_node.DirectSubprocessProvider") as MockProvider,
            patch("nuke_nodes.nuke_script_node.GriptapeNodes") as MockGT,
        ):
            MockGT.ConfigManager.return_value.get_config_value.return_value = None
            MockGT.handle_request.return_value = MagicMock(spec=WriteFileResultSuccess)
            instance = MockProvider.return_value
            instance.submit.return_value = "handle-456"
            instance.result.return_value = fake_result

            node.process()

        call_kwargs = node._set_status_results.call_args.kwargs
        assert call_kwargs["was_successful"] is False
        assert "1" in call_kwargs["result_details"]
        node._handle_failure_exception.assert_called_once()

    def test_sequence_output_produces_list_artifact(self, tmp_path: Path) -> None:
        from execution.provider import JobResult, JobStatus
        from script_parser.annotation import GriptapeAnnotation

        nk_file = tmp_path / "test.nk"
        nk_file.write_text("")

        # Create fake frame files
        f1 = tmp_path / "frame.0001.png"
        f2 = tmp_path / "frame.0002.png"
        f1.write_bytes(b"\x89PNG")
        f2.write_bytes(b"\x89PNG")

        node = _make_node()
        node._annotations = [
            GriptapeAnnotation(node_name="Write1", role="output", gt_name="frames", gt_type="ImageSequenceArtifact")
        ]
        node._expose_knobs = []

        node.get_parameter_value = MagicMock(
            side_effect=lambda name: {
                "script_path": str(nk_file),
                "nuke_executable": "/usr/bin/nuke",
                "frame_start": 1001,
                "frame_end": 1002,
            }.get(name)
        )

        fake_result = JobResult(
            handle="handle-seq",
            status=JobStatus.SUCCEEDED,
            return_code=0,
            log=[],
            outputs={"frames": [str(f1), str(f2)]},
        )

        saved1, saved2 = MagicMock(), MagicMock()
        saved1.location = "http://s/f1.png"
        saved2.location = "http://s/f2.png"
        # seq_dest: used by process() to resolve the sequence directory
        seq_dest = MagicMock()
        seq_dest.resolve.return_value = "/fake/temp/frames_frame.png"
        dest1, dest2 = MagicMock(), MagicMock()
        dest1.write_bytes.return_value = saved1
        dest2.write_bytes.return_value = saved2
        mock_dest_cls = MagicMock()
        mock_dest_cls.from_situation.side_effect = [seq_dest, dest1, dest2]
        mock_file = MagicMock()
        mock_file.read_bytes.return_value = b"\x89PNG"

        with (
            patch("nuke_nodes.nuke_script_node.DirectSubprocessProvider") as MockProvider,
            patch("nuke_nodes.nuke_script_node.GriptapeNodes") as MockGT,
            patch("nuke_nodes.nuke_script_node.File", return_value=mock_file),
            patch("nuke_nodes.nuke_script_node.ProjectFileDestination", mock_dest_cls),
        ):
            MockGT.ConfigManager.return_value.get_config_value.return_value = None
            # final_file_path for the .empty sentinel — seq_dir is derived from its parent
            write_result = MagicMock(spec=WriteFileResultSuccess)
            write_result.final_file_path = "/fake/temp/.empty"
            MockGT.handle_request.return_value = write_result
            instance = MockProvider.return_value
            instance.submit.return_value = "handle-seq"
            instance.result.return_value = fake_result

            node.process()

        from griptape.artifacts import ListArtifact

        output_val = node.parameter_output_values.__setitem__.call_args[0][1]
        assert isinstance(output_val, ListArtifact)
        assert len(output_val.value) == 2

    def test_applies_zero_float_knob_override(self, tmp_path: Path) -> None:
        from execution.provider import JobResult, JobStatus
        from script_parser.annotation import ExposedKnob

        nk_file = tmp_path / "test.nk"
        nk_file.write_text("")

        node = _make_node()
        node._annotations = []
        ek = ExposedKnob(
            source_node="Grade1",
            knob_ref="Grade1.multiply",
            target_node="Grade1",
            target_knob="multiply",
            param_name="Grade1_multiply",
            knob_type="AColor_Knob",
        )
        node._expose_knobs = [ek]

        node.get_parameter_value = MagicMock(
            side_effect=lambda name: {
                "script_path": str(nk_file),
                "nuke_executable": "/usr/bin/nuke",
                "frame_start": 1001,
                "frame_end": 1001,
                "Grade1_multiply": 0.0,
            }.get(name)
        )

        fake_result = JobResult(
            handle="handle-789",
            status=JobStatus.SUCCEEDED,
            return_code=0,
            log=[],
            outputs={},
        )

        with (
            patch("nuke_nodes.nuke_script_node.DirectSubprocessProvider") as MockProvider,
            patch("nuke_nodes.nuke_script_node.GriptapeNodes") as MockGT,
        ):
            MockGT.ConfigManager.return_value.get_config_value.return_value = None
            MockGT.handle_request.return_value = MagicMock(spec=WriteFileResultSuccess)
            instance = MockProvider.return_value
            instance.submit.return_value = "handle-789"
            instance.result.return_value = fake_result

            node.process()

        manifest = instance.submit.call_args.args[0]
        assert len(manifest.knob_overrides) == 1
        assert manifest.knob_overrides[0].node == "Grade1"
        assert manifest.knob_overrides[0].knob == "multiply"
        assert manifest.knob_overrides[0].value == pytest.approx(0.0)

    def test_mid_loop_failure_still_cleans_up_earlier_files(self, tmp_path: Path) -> None:
        from script_parser.annotation import GriptapeAnnotation

        nk_file = tmp_path / "test.nk"
        nk_file.write_text("")

        node = _make_node()
        node._annotations = [
            GriptapeAnnotation(node_name="Write1", role="output", gt_name="out1", gt_type="ImageArtifact"),
            GriptapeAnnotation(node_name="Write2", role="output", gt_name="out2", gt_type="ImageArtifact"),
        ]
        node._expose_knobs = []
        node.get_parameter_value = MagicMock(
            side_effect=lambda name: {
                "script_path": str(nk_file),
                "nuke_executable": "/usr/bin/nuke",
                "frame_start": 1001,
                "frame_end": 1001,
            }.get(name)
        )

        resolve_path_1 = "/fake/temp/out1_resolve.png"
        canonical_path_1 = "/fake/temp/out1_canonical.png"
        dest1, dest2 = MagicMock(), MagicMock()
        dest1.resolve.return_value = resolve_path_1
        dest2.resolve.return_value = "/fake/temp/out2_resolve.png"
        mock_dest_cls = MagicMock()
        mock_dest_cls.from_situation.side_effect = [dest1, dest2]

        write_success = MagicMock(spec=WriteFileResultSuccess)
        write_success.final_file_path = canonical_path_1
        write_failure = MagicMock(spec=WriteFileResultFailure)

        call_count = {"n": 0}

        def handle_request_side_effect(request: object) -> object:
            if isinstance(request, WriteFileRequest):
                call_count["n"] += 1
                return write_success if call_count["n"] == 1 else write_failure
            return MagicMock(spec=WriteFileResultSuccess)

        with (
            patch("nuke_nodes.nuke_script_node.GriptapeNodes") as MockGT,
            patch("nuke_nodes.nuke_script_node.ProjectFileDestination", mock_dest_cls),
            patch("nuke_nodes.nuke_script_node.DirectSubprocessProvider"),
        ):
            MockGT.ConfigManager.return_value.get_config_value.return_value = None
            MockGT.handle_request.side_effect = handle_request_side_effect

            with pytest.raises(RuntimeError):
                node.process()

        delete_calls = [c for c in MockGT.handle_request.call_args_list if isinstance(c.args[0], DeleteFileRequest)]
        deleted_paths = {c.args[0].path for c in delete_calls}
        assert canonical_path_1 in deleted_paths
        assert resolve_path_1 not in deleted_paths
