"""Tests for the shared parameter-value reader.

The reader is what stops ``NukeLoadWorkflowRequest`` and ``NukeGetParameterValuesRequest``
from disagreeing about what a parameter holds, so its behaviour is asserted here once rather
than twice through the two verbs that use it.
"""

from __future__ import annotations

from typing import Any

import pytest
from griptape_nodes.common.sequences.models import MissingItemPolicy, Sequence, SequenceEntry
from griptape_nodes.retained_mode.events.os_events import (
    ScanSequencesRequest,
    ScanSequencesResultFailure,
    ScanSequencesResultSuccess,
    SequenceScanFailureReason,
)
from griptape_nodes.retained_mode.events.parameter_events import (
    GetParameterValueRequest,
    GetParameterValueResultFailure,
    GetParameterValueResultSuccess,
    SetParameterValueRequest,
    SetParameterValueResultFailure,
    SetParameterValueResultSuccess,
)

from nuke_host_api import engine, parameter_values
from nuke_host_api.protocol import PARAMETER_SECTIONS, ParameterSection, ValueType
from tests.unit.host_api_fakes import SHAPE, respond_to_get_value, use_engine


class TestReadSections:
    async def test_both_sections_are_read_when_both_are_requested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {GetParameterValueRequest: respond_to_get_value})

        inputs, outputs, unavailable = await parameter_values.read_sections(SHAPE, list(PARAMETER_SECTIONS))

        assert inputs["Start Flow"]["topic"]["value_type"] == ValueType.TEXT
        assert outputs["End Flow"]["was_successful"]["value_type"] == ValueType.BOOL
        assert unavailable == []

    async def test_a_section_not_requested_comes_back_empty_and_unread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty map rather than a missing key, so no caller has to tell the two apart."""
        engine = use_engine(monkeypatch, {GetParameterValueRequest: respond_to_get_value})

        inputs, outputs, _ = await parameter_values.read_sections(SHAPE, [ParameterSection.INPUTS])

        assert inputs
        assert outputs == {}
        read = {r.parameter_name for r in engine.requests if isinstance(r, GetParameterValueRequest)}
        assert read == {"topic", "plate"}

    async def test_an_unreadable_parameter_is_tagged_with_the_section_it_came_from(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def respond(request: GetParameterValueRequest) -> Any:
            if request.parameter_name == "was_successful":
                return GetParameterValueResultFailure(result_details="node was deleted mid-read")
            return respond_to_get_value(request)

        use_engine(monkeypatch, {GetParameterValueRequest: respond})

        _, outputs, unavailable = await parameter_values.read_sections(SHAPE, list(PARAMETER_SECTIONS))

        assert "was_successful" not in outputs.get("End Flow", {})
        assert unavailable == [
            {
                "section": ParameterSection.OUTPUTS,
                "node": "End Flow",
                "parameter": "was_successful",
                "reason": "node was deleted mid-read",
            }
        ]

    async def test_a_value_the_engine_holds_as_none_is_a_value_not_a_miss(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unset knob and one that could not be read mean different things to a host."""
        use_engine(monkeypatch, {GetParameterValueRequest: respond_to_get_value})

        inputs, _, unavailable = await parameter_values.read_sections(SHAPE, [ParameterSection.INPUTS])

        assert inputs["Start Flow"]["plate"]["value"] is None
        assert unavailable == []

    async def test_a_value_with_no_host_form_is_unavailable_with_a_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def respond(request: GetParameterValueRequest) -> Any:
            if request.parameter_name == "plate":
                return GetParameterValueResultSuccess(
                    input_types=["ImageUrlArtifact"],
                    type="ImageUrlArtifact",
                    output_type="ImageUrlArtifact",
                    value="https://cdn.example.com/plate.png",
                    result_details="ok",
                )
            return respond_to_get_value(request)

        use_engine(monkeypatch, {GetParameterValueRequest: respond})

        inputs, _, unavailable = await parameter_values.read_sections(SHAPE, [ParameterSection.INPUTS])

        assert "plate" not in inputs["Start Flow"]
        assert [(entry["parameter"], "URL" in entry["reason"]) for entry in unavailable] == [("plate", True)]

    async def test_an_empty_shape_reads_nothing_and_reports_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, {})

        inputs, outputs, unavailable = await parameter_values.read_sections({}, list(PARAMETER_SECTIONS))

        assert (inputs, outputs, unavailable) == ({}, {}, [])
        assert engine.requests == []

    async def test_control_parameters_are_never_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Execution wiring is not data, and the normalizer has no case for its type."""
        engine_fake = use_engine(monkeypatch, {GetParameterValueRequest: respond_to_get_value})

        await parameter_values.read_sections(SHAPE, list(PARAMETER_SECTIONS))

        read = {r.parameter_name for r in engine_fake.requests if isinstance(r, GetParameterValueRequest)}
        assert not read & {"exec_in", "exec_out"}


class TestApplyInputs:
    """Shared by NukeExecuteWorkflowRequest and NukeSetParameterValuesRequest.

    Asserted here once, against the module both verbs call into, rather than through either
    handler, so the two cannot silently diverge on what "applied" and "rejected" mean.
    """

    async def test_applied_and_rejected_inputs_are_tracked_separately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def respond(request: SetParameterValueRequest) -> Any:
            if request.parameter_name == "good":
                return SetParameterValueResultSuccess(finalized_value=1, data_type="int", result_details="ok")
            return SetParameterValueResultFailure(result_details="rejected: wrong type")

        use_engine(monkeypatch, {SetParameterValueRequest: respond})

        applied, rejected = await parameter_values.apply_inputs(
            {"Node A": {"good": 1, "bad": "nope"}}, {("Node A", "good"): "int", ("Node A", "bad"): "int"}
        )

        assert applied == [{"node": "Node A", "parameter": "good"}]
        assert rejected == [{"node": "Node A", "parameter": "bad", "reason": "rejected: wrong type"}]

    async def test_a_media_entry_a_host_read_back_is_sent_to_the_engine_as_its_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine_fake = use_engine(
            monkeypatch,
            {
                SetParameterValueRequest: SetParameterValueResultSuccess(
                    finalized_value=None, data_type="ImageUrlArtifact", result_details="ok"
                )
            },
        )

        await parameter_values.apply_inputs(
            {"Start Flow": {"plate": {"path": "/show/plate.exr", "format": "exr", "first": None, "last": None}}},
            {("Start Flow", "plate"): "ImageUrlArtifact"},
        )

        assert [request.value for request in engine_fake.requests] == ["/show/plate.exr"]

    async def test_a_non_dict_parameters_value_is_rejected_without_calling_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine_fake = use_engine(monkeypatch, {})

        applied, rejected = await parameter_values.apply_inputs({"Node A": "not a dict"}, {("Node A", "good"): "int"})  # type: ignore[arg-type]

        assert applied == []
        assert rejected == [{"node": "Node A", "parameter": "*", "reason": "Expected an object of parameters."}]
        assert engine_fake.requests == []

    async def test_a_pair_outside_the_allow_list_is_rejected_without_calling_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine_fake = use_engine(monkeypatch, {})

        applied, rejected = await parameter_values.apply_inputs({"Node A": {"secret": 1}}, {})

        assert applied == []
        assert rejected == [
            {"node": "Node A", "parameter": "secret", "reason": "Not a declared input parameter of this workflow."}
        ]
        assert engine_fake.requests == []


class TestApplySequenceInputs:
    """A host holds no Sequence, so the path and range it read are rescanned into one."""

    PLATE = {("Start Flow", "plate"): "Sequence"}

    @staticmethod
    def _scanned(*, has_entries: bool = True) -> ScanSequencesResultSuccess:
        sequence = Sequence(
            entries=[SequenceEntry(number=1001, padded_number="1001", path="/show/plate/frame_1001.png")]
            if has_entries
            else [],
            first=1001,
            last=1002,
            discovered_first=1001,
            discovered_last=1002,
            padding=4,
            pattern="frame_####.png",
            directory="/show/plate",
            policy=MissingItemPolicy.SKIP,
        )
        return ScanSequencesResultSuccess(
            sequences=[sequence],
            has_entries=has_entries,
            directory_had_matching_files=has_entries,
            discovered_first=1001,
            discovered_last=1002,
            result_details="scanned",
        )

    @staticmethod
    def _engine(monkeypatch: pytest.MonkeyPatch, scan: Any) -> Any:
        return use_engine(
            monkeypatch,
            {
                ScanSequencesRequest: scan,
                SetParameterValueRequest: lambda req: SetParameterValueResultSuccess(
                    finalized_value=req.value, data_type="Sequence", result_details="set"
                ),
            },
        )

    async def test_an_entry_a_host_read_back_is_rescanned_over_its_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scanned = self._scanned()
        engine_fake = self._engine(monkeypatch, scanned)
        entry = {"path": "/show/plate/frame_####.png", "format": "png", "first": 1001, "last": 1002}

        applied, rejected = await parameter_values.apply_inputs({"Start Flow": {"plate": entry}}, self.PLATE)

        scan, set_value = engine_fake.requests
        assert (scan.path, scan.start_number, scan.end_number) == ("/show/plate/frame_####.png", 1001, 1002)
        assert scan.policy == MissingItemPolicy.SKIP
        assert set_value.value is scanned.sequences[0]
        assert (applied, rejected) == ([{"node": "Start Flow", "parameter": "plate"}], [])

    async def test_a_bare_pattern_is_rescanned_over_every_frame(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine_fake = self._engine(monkeypatch, self._scanned())

        await parameter_values.apply_inputs({"Start Flow": {"plate": "/show/plate/frame_####.png"}}, self.PLATE)

        scan = engine_fake.requests[0]
        assert (scan.path, scan.start_number, scan.end_number) == ("/show/plate/frame_####.png", None, None)

    @pytest.mark.parametrize("unset", [None, ""])
    async def test_an_unset_sequence_is_set_without_a_scan(self, monkeypatch: pytest.MonkeyPatch, unset: Any) -> None:
        engine_fake = self._engine(monkeypatch, self._scanned())

        await parameter_values.apply_inputs({"Start Flow": {"plate": unset}}, self.PLATE)

        assert [type(request) for request in engine_fake.requests] == [SetParameterValueRequest]
        assert engine_fake.requests[0].value is None

    async def test_a_list_parameter_scans_each_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine_fake = self._engine(monkeypatch, self._scanned())
        entries = [{"path": "/a/x_####.png", "first": 1, "last": 2}, {"path": "/a/y_####.png"}]

        await parameter_values.apply_inputs(
            {"Start Flow": {"plates": entries}}, {("Start Flow", "plates"): "list[Sequence]"}
        )

        scans = [request.path for request in engine_fake.requests if isinstance(request, ScanSequencesRequest)]
        assert scans == ["/a/x_####.png", "/a/y_####.png"]
        assert len(engine_fake.requests[-1].value) == 2

    @pytest.mark.parametrize(
        ("value", "reason"),
        [
            ({"format": "png"}, "media entry or a path"),
            (7, "media entry or a path"),
            ({"path": "/a/x_####.png", "first": "1001"}, "whole numbers"),
            ({"path": "/a/x_####.png", "last": True}, "whole numbers"),
        ],
    )
    async def test_a_malformed_sequence_is_rejected_without_a_scan(
        self, monkeypatch: pytest.MonkeyPatch, value: Any, reason: str
    ) -> None:
        engine_fake = self._engine(monkeypatch, self._scanned())

        applied, rejected = await parameter_values.apply_inputs({"Start Flow": {"plate": value}}, self.PLATE)

        assert applied == []
        assert reason in rejected[0]["reason"]
        assert engine_fake.requests == []

    async def test_a_scan_that_finds_no_frames_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine_fake = self._engine(monkeypatch, self._scanned(has_entries=False))

        _, rejected = await parameter_values.apply_inputs({"Start Flow": {"plate": "/a/x_####.png"}}, self.PLATE)

        assert rejected == [
            {"node": "Start Flow", "parameter": "plate", "reason": "No frames found at '/a/x_####.png'."}
        ]
        assert not any(isinstance(request, SetParameterValueRequest) for request in engine_fake.requests)

    async def test_a_scan_the_engine_refuses_is_rejected_with_its_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        refusal = ScanSequencesResultFailure(
            failure_reason=SequenceScanFailureReason.INVALID_TEMPLATE, result_details="two frame tokens"
        )
        self._engine(monkeypatch, refusal)

        _, rejected = await parameter_values.apply_inputs({"Start Flow": {"plate": "/a/x_##_##.png"}}, self.PLATE)

        assert rejected[0]["reason"] == "two frame tokens"


class TestUnaddressableInputsReason:
    """Shared by NukeExecuteWorkflowRequest and NukeSetParameterValuesRequest.

    Each caller supplies its own ``no_inputs_remedy``, naming the one alternative it still has
    once its own inputs turn out to be unaddressable, or leaves it unset when it has none.
    """

    def test_nothing_is_wrong_when_the_workflow_declares_the_requested_inputs(self) -> None:
        found = engine.WorkflowLookup(entry={"name": "wf1"}, registry_readable=True)

        reason = parameter_values.unaddressable_inputs_reason(
            "wf1", found, {("Start Flow", "topic")}, no_inputs_remedy="do nothing"
        )

        assert reason is None

    def test_an_unreadable_registry_names_a_retry_and_the_callers_own_remedy(self) -> None:
        found = engine.WorkflowLookup(entry=None, registry_readable=False)

        reason = parameter_values.unaddressable_inputs_reason(
            "wf1", found, set(), no_inputs_remedy="send no values, since there is nothing else to do"
        )

        assert reason is not None
        assert "could not read the workflow registry" in reason.because
        assert "send no values, since there is nothing else to do" in reason.because
        assert reason.error is RuntimeError

    def test_an_unreadable_registry_names_only_a_retry_when_the_caller_has_no_remedy(self) -> None:
        """NukeSetParameterValuesRequest's case: no fallback to offer, so none is named."""
        found = engine.WorkflowLookup(entry=None, registry_readable=False)

        reason = parameter_values.unaddressable_inputs_reason("wf1", found, set())

        assert reason is not None
        assert reason.because.endswith("could not be checked against it. Retry.")

    def test_a_loaded_id_missing_from_a_readable_registry_names_a_reload_not_the_callers_remedy(self) -> None:
        found = engine.WorkflowLookup(entry=None, registry_readable=True)

        reason = parameter_values.unaddressable_inputs_reason(
            "wf1", found, set(), no_inputs_remedy="send no values, since there is nothing else to do"
        )

        assert reason is not None
        assert "no longer in the registry" in reason.because
        assert "NukeLoadWorkflowRequest" in reason.because
        assert "send no values" not in reason.because
        assert reason.error is KeyError

    def test_a_graph_with_no_declared_inputs_names_the_callers_own_remedy(self) -> None:
        found = engine.WorkflowLookup(entry={"name": "Untitled"}, registry_readable=True)

        reason = parameter_values.unaddressable_inputs_reason(
            "unsaved:9f0c", found, set(), no_inputs_remedy="do nothing"
        )

        assert reason is not None
        assert "declares no input parameters" in reason.because
        assert "do nothing" in reason.because
        assert reason.error is RuntimeError

    def test_a_graph_with_no_declared_inputs_names_only_the_reload_path_when_the_caller_has_no_remedy(self) -> None:
        """NukeSetParameterValuesRequest's case: no fallback to offer, so none is named."""
        found = engine.WorkflowLookup(entry={"name": "Untitled"}, registry_readable=True)

        reason = parameter_values.unaddressable_inputs_reason("unsaved:9f0c", found, set())

        assert reason is not None
        assert reason.because.endswith("save it and load it by id.")
