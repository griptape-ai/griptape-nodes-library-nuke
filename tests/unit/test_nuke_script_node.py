"""Unit tests for NukeScriptNode — pure logic only, no Nuke process spawned."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nuke_nodes.nuke_script_node import _coerce_knob_value

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Module-level pure functions
# ---------------------------------------------------------------------------


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

        with (
            patch("nuke_nodes.nuke_script_node.DirectSubprocessProvider") as MockProvider,
            patch("nuke_nodes.nuke_script_node.GriptapeNodes") as MockGT,
        ):
            MockGT.ConfigManager.return_value.get_config_value.return_value = None
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
            instance = MockProvider.return_value
            instance.submit.return_value = "handle-456"
            instance.result.return_value = fake_result

            node.process()

        call_kwargs = node._set_status_results.call_args.kwargs
        assert call_kwargs["was_successful"] is False
        assert "1" in call_kwargs["result_details"]
        node._handle_failure_exception.assert_called_once()

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
            instance = MockProvider.return_value
            instance.submit.return_value = "handle-789"
            instance.result.return_value = fake_result

            node.process()

        manifest = instance.submit.call_args.args[0]
        assert len(manifest.knob_overrides) == 1
        assert manifest.knob_overrides[0].node == "Grade1"
        assert manifest.knob_overrides[0].knob == "multiply"
        assert manifest.knob_overrides[0].value == pytest.approx(0.0)
