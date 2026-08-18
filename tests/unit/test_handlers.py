"""Tests for the translation handlers.

Focused on the parts that decide what a host sees: how the engine's workflow shape is
parsed, how ports are narrowed, and how negotiation refuses an unsupported host.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from griptape_nodes.retained_mode.events.context_events import (
    GetWorkflowContextRequest,
    GetWorkflowContextSuccess,
)
from griptape_nodes.retained_mode.events.execution_events import (
    CancelFlowRequest,
    CancelFlowResultFailure,
    CancelFlowResultSuccess,
    GetFlowStateRequest,
    GetFlowStateResultSuccess,
    StartFlowRequest,
    StartFlowResultFailure,
    StartFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.flow_events import (
    GetTopLevelFlowRequest,
    GetTopLevelFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.parameter_events import (
    GetParameterValueRequest,
    GetParameterValueResultSuccess,
    SetParameterValueRequest,
    SetParameterValueResultFailure,
    SetParameterValueResultSuccess,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    ListAllWorkflowsRequest,
    ListAllWorkflowsResultFailure,
    ListAllWorkflowsResultSuccess,
    RunWorkflowFromRegistryRequest,
    RunWorkflowFromRegistryResultFailure,
    RunWorkflowFromRegistryResultSuccess,
)

from nuke_host_api import handlers
from nuke_host_api.events import (
    NukeCancelExecutionRequest,
    NukeCancelExecutionResultFailure,
    NukeCancelExecutionResultSuccess,
    NukeConnectRequest,
    NukeConnectResultFailure,
    NukeConnectResultSuccess,
    NukeDescribeWorkflowRequest,
    NukeDescribeWorkflowResultFailure,
    NukeDescribeWorkflowResultSuccess,
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultFailure,
    NukeExecuteWorkflowResultSuccess,
    NukeGetExecutionStateRequest,
    NukeGetExecutionStateResultFailure,
    NukeGetExecutionStateResultSuccess,
    NukeListWorkflowsRequest,
    NukeListWorkflowsResultFailure,
    NukeListWorkflowsResultSuccess,
)
from nuke_host_api.protocol import PROTOCOL_VERSION, VALUE_TYPES, ExecutionState, ValueType

SHAPE = {
    "inputs": {
        "Start Flow": {
            "exec_out": {"type": "parametercontroltype"},
            "topic": {"type": "str"},
            "plate": {"type": "ImageUrlArtifact"},
        }
    },
    "outputs": {
        "End Flow": {
            "exec_in": {"type": "parametercontroltype"},
            "was_successful": {"type": "bool"},
            "mixed_audio": {"type": "AudioUrlArtifact"},
        }
    },
}


class TestWorkflowShape:
    """The engine sends this field as a dict, a JSON string, or not at all."""

    def test_a_dict_passes_through(self) -> None:
        assert handlers._workflow_shape({"workflow_shape": SHAPE}) == SHAPE

    def test_a_json_string_is_parsed(self) -> None:
        """The case that silently produced zero ports for every workflow."""
        assert handlers._workflow_shape({"workflow_shape": json.dumps(SHAPE)}) == SHAPE

    @pytest.mark.parametrize("raw", [None, "", "   ", "not json at all", "[]", "123"])
    def test_anything_else_is_an_empty_shape(self, raw: Any) -> None:
        assert handlers._workflow_shape({"workflow_shape": raw}) == {}

    def test_a_missing_field_is_an_empty_shape(self) -> None:
        assert handlers._workflow_shape({}) == {}


class TestPorts:
    """Ports are the only workflow detail a host sees."""

    def test_control_parameters_are_dropped(self) -> None:
        """exec_in and exec_out are execution wiring, not data."""
        names = {port["parameter"] for port in handlers._ports(SHAPE["inputs"])}
        assert "exec_out" not in names
        assert names == {"topic", "plate"}

    def test_node_and_parameter_are_split_out(self) -> None:
        """run_workflow addresses inputs by the pair, so it cannot be a joined string."""
        port = next(p for p in handlers._ports(SHAPE["inputs"]) if p["parameter"] == "topic")
        assert port["node"] == "Start Flow"
        assert port["parameter"] == "topic"
        assert port["name"] == "Start Flow.topic"

    def test_types_are_narrowed_to_the_closed_set(self) -> None:
        types = {port["parameter"]: port["type"] for port in handlers._ports(SHAPE["inputs"])}
        assert types == {"topic": ValueType.TEXT, "plate": ValueType.IMAGE}

    def test_an_out_of_scope_engine_type_degrades(self) -> None:
        """AudioUrlArtifact is outside the v1 set, so it must not leak through."""
        types = {port["parameter"]: port["type"] for port in handlers._ports(SHAPE["outputs"])}
        assert types["mixed_audio"] == ValueType.FILE
        assert all(port["type"] in VALUE_TYPES for port in handlers._ports(SHAPE["outputs"]))

    @pytest.mark.parametrize("section", [None, {}, "string", 7, {"Node": "not a dict"}, {"Node": {"p": "not a dict"}}])
    def test_malformed_sections_yield_no_ports_rather_than_raising(self, section: Any) -> None:
        assert handlers._ports(section) == []


class FakeEngine:
    """Minimal facade stand-in for handlers that only need version and session lookups."""

    @staticmethod
    def handle_request(request: Any) -> Any:  # noqa: ARG004
        from griptape_nodes.retained_mode.events.app_events import GetEngineVersionResultSuccess

        return GetEngineVersionResultSuccess(major=0, minor=97, patch=0, result_details="ok")

    @staticmethod
    def get_session_id() -> str:
        return "session-abc"

    @staticmethod
    def get_engine_id() -> str:
        return "engine-xyz"


class TestConnect:
    @pytest.fixture(autouse=True)
    def _fake_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(handlers, "GriptapeNodes", FakeEngine)

    def test_a_matching_version_connects(self) -> None:
        result = handlers.handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION]))
        assert isinstance(result, NukeConnectResultSuccess)
        assert result.protocol_version == PROTOCOL_VERSION
        assert result.value_types == list(VALUE_TYPES)

    def test_the_event_topic_is_handed_over(self) -> None:
        """A host cannot derive this, so failing to return it strands notifications."""
        result = handlers.handle_connect(NukeConnectRequest(client_protocol_versions=[PROTOCOL_VERSION]))
        assert isinstance(result, NukeConnectResultSuccess)
        assert result.event_topic == "sessions/session-abc/response"

    def test_an_empty_offer_assumes_the_current_version(self) -> None:
        """Keeps a bare connectivity check working."""
        result = handlers.handle_connect(NukeConnectRequest())
        assert isinstance(result, NukeConnectResultSuccess)

    def test_an_unsupported_version_is_refused_with_the_window(self) -> None:
        result = handlers.handle_connect(NukeConnectRequest(client_protocol_versions=[99]))
        assert isinstance(result, NukeConnectResultFailure)
        assert result.supported_protocol_versions
        assert "99" in str(result.result_details)

    def test_the_highest_mutual_version_wins(self) -> None:
        result = handlers.handle_connect(NukeConnectRequest(client_protocol_versions=[99, PROTOCOL_VERSION]))
        assert isinstance(result, NukeConnectResultSuccess)
        assert result.protocol_version == PROTOCOL_VERSION

    def test_a_wrong_request_type_raises(self) -> None:
        """Guards against a registry mix-up routing the wrong payload here."""
        with pytest.raises(TypeError):
            handlers.handle_connect(NukeConnectRequest)  # type: ignore[arg-type]


class TestLibraryVersion:
    """protocol.py's old LIBRARY_VERSION constant drifted from the manifest; this reads it live."""

    def test_reads_the_shipped_version_from_the_manifest(self) -> None:
        handlers._library_version.cache_clear()
        assert handlers._library_version() == "0.3.0"

    def test_degrades_to_unknown_when_the_manifest_is_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        handlers._library_version.cache_clear()
        monkeypatch.setattr(handlers, "_LIBRARY_MANIFEST_PATH", tmp_path / "does_not_exist.json")
        try:
            assert handlers._library_version() == "unknown"
        finally:
            handlers._library_version.cache_clear()

    def test_degrades_to_unknown_when_the_manifest_is_malformed_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        malformed = tmp_path / "griptape-nodes-library.json"
        malformed.write_text("{not valid json")
        handlers._library_version.cache_clear()
        monkeypatch.setattr(handlers, "_LIBRARY_MANIFEST_PATH", malformed)
        try:
            assert handlers._library_version() == "unknown"
        finally:
            handlers._library_version.cache_clear()

    def test_degrades_to_unknown_when_the_manifest_has_no_library_version_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        missing_key = tmp_path / "griptape-nodes-library.json"
        missing_key.write_text(json.dumps({"metadata": {}}))
        handlers._library_version.cache_clear()
        monkeypatch.setattr(handlers, "_LIBRARY_MANIFEST_PATH", missing_key)
        try:
            assert handlers._library_version() == "unknown"
        finally:
            handlers._library_version.cache_clear()


class FakeDispatchEngine:
    """Dispatches handle_request by request type, recording call order.

    A response may be a real result instance, reused for every call of that type, or a
    callable that receives the request and computes one, needed when the same request
    type is issued more than once with different outcomes (e.g. one SetParameterValueRequest
    per input).
    """

    def __init__(self, responses: dict[type, Any]) -> None:
        self._responses = responses
        self.requests: list[Any] = []

    def handle_request(self, request: Any) -> Any:
        self.requests.append(request)
        response = self._responses.get(type(request))
        if response is None:
            msg = f"FakeDispatchEngine has no response configured for {type(request).__name__}"
            raise AssertionError(msg)
        return response(request) if callable(response) else response


class TestExecuteWorkflow:
    def test_a_successful_run_calls_the_engine_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = FakeDispatchEngine(
            {
                RunWorkflowFromRegistryRequest: RunWorkflowFromRegistryResultSuccess(result_details="loaded"),
                SetParameterValueRequest: lambda req: SetParameterValueResultSuccess(
                    finalized_value=req.value, data_type="str", result_details="set"
                ),
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                StartFlowRequest: StartFlowResultSuccess(result_details="started"),
            }
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_execute_workflow(
            NukeExecuteWorkflowRequest(workflow_id="wf1", inputs={"Start Flow": {"topic": "hello"}})
        )

        assert isinstance(result, NukeExecuteWorkflowResultSuccess)
        assert result.state == ExecutionState.RUNNING
        assert result.applied_inputs == [{"node": "Start Flow", "parameter": "topic"}]
        assert result.rejected_inputs == []

        request_types = [type(request) for request in engine.requests]
        assert request_types.index(RunWorkflowFromRegistryRequest) < request_types.index(SetParameterValueRequest)
        assert request_types.index(SetParameterValueRequest) < request_types.index(StartFlowRequest)

        load_request = next(r for r in engine.requests if isinstance(r, RunWorkflowFromRegistryRequest))
        assert load_request.run_with_clean_slate is True

    def test_short_circuits_when_the_engine_cannot_load_the_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = FakeDispatchEngine(
            {RunWorkflowFromRegistryRequest: RunWorkflowFromRegistryResultFailure(result_details="not found")}
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="ghost"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert len(engine.requests) == 1, "must not touch inputs or start a flow it never loaded"

    def test_short_circuits_when_the_loaded_workflow_has_no_top_level_flow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = FakeDispatchEngine(
            {
                RunWorkflowFromRegistryRequest: RunWorkflowFromRegistryResultSuccess(result_details="loaded"),
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name=None, result_details="ok"),
            }
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)
        assert not any(isinstance(request, StartFlowRequest) for request in engine.requests)

    def test_short_circuits_when_the_engine_refuses_to_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = FakeDispatchEngine(
            {
                RunWorkflowFromRegistryRequest: RunWorkflowFromRegistryResultSuccess(result_details="loaded"),
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                StartFlowRequest: StartFlowResultFailure(result_details="validation failed", validation_exceptions=[]),
            }
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeExecuteWorkflowResultFailure)


class TestApplyInputs:
    def test_applied_and_rejected_inputs_are_tracked_separately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def respond(request: SetParameterValueRequest) -> Any:
            if request.parameter_name == "good":
                return SetParameterValueResultSuccess(finalized_value=1, data_type="int", result_details="ok")
            return SetParameterValueResultFailure(result_details="rejected: wrong type")

        engine = FakeDispatchEngine({SetParameterValueRequest: respond})
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        applied, rejected = handlers._apply_inputs({"Node A": {"good": 1, "bad": "nope"}})

        assert applied == [{"node": "Node A", "parameter": "good"}]
        assert rejected == [{"node": "Node A", "parameter": "bad", "reason": "rejected: wrong type"}]

    def test_a_non_dict_parameters_value_is_rejected_without_calling_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = FakeDispatchEngine({})
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        applied, rejected = handlers._apply_inputs({"Node A": "not a dict"})  # type: ignore[arg-type]

        assert applied == []
        assert rejected == [{"node": "Node A", "parameter": "*", "reason": "Expected an object of parameters."}]
        assert engine.requests == []


class TestListWorkflows:
    def test_lists_every_workflow_with_its_runnable_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(handlers, "_is_runnable", lambda entry: (entry["id"] == "runnable_one", "not on disk"))
        table = {
            "runnable_one": {"id": "runnable_one", "name": "Runnable", "description": "d1"},
            "broken_one": {"id": "broken_one", "name": "Broken", "description": "d2"},
        }
        engine = FakeDispatchEngine(
            {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows=table, result_details="ok")}
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_list_workflows(NukeListWorkflowsRequest(runnable_only=False))

        assert isinstance(result, NukeListWorkflowsResultSuccess)
        assert {workflow["id"] for workflow in result.workflows} == {"runnable_one", "broken_one"}

    def test_runnable_only_filters_out_unrunnable_workflows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(handlers, "_is_runnable", lambda entry: (entry["id"] == "runnable_one", "not on disk"))
        table = {
            "runnable_one": {"id": "runnable_one"},
            "broken_one": {"id": "broken_one"},
        }
        engine = FakeDispatchEngine(
            {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows=table, result_details="ok")}
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_list_workflows(NukeListWorkflowsRequest(runnable_only=True))

        assert isinstance(result, NukeListWorkflowsResultSuccess)
        assert {workflow["id"] for workflow in result.workflows} == {"runnable_one"}

    def test_a_registry_read_failure_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = FakeDispatchEngine(
            {ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="registry unavailable")}
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_list_workflows(NukeListWorkflowsRequest())

        assert isinstance(result, NukeListWorkflowsResultFailure)


class TestDescribeWorkflow:
    def test_describes_inputs_and_outputs_from_the_workflow_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        table = {"wf1": {"name": "WF One", "description": "d", "workflow_shape": SHAPE}}
        engine = FakeDispatchEngine(
            {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows=table, result_details="ok")}
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_describe_workflow(NukeDescribeWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeDescribeWorkflowResultSuccess)
        assert {port["parameter"] for port in result.inputs} == {"topic", "plate"}
        assert {port["parameter"] for port in result.outputs} == {"was_successful", "mixed_audio"}

    def test_an_unknown_workflow_id_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = FakeDispatchEngine(
            {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows={}, result_details="ok")}
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_describe_workflow(NukeDescribeWorkflowRequest(workflow_id="ghost"))

        assert isinstance(result, NukeDescribeWorkflowResultFailure)
        assert result.workflow_id == "ghost"

    def test_a_registry_read_failure_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = FakeDispatchEngine(
            {ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="registry unavailable")}
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_describe_workflow(NukeDescribeWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeDescribeWorkflowResultFailure)


class TestIsRunnable:
    def test_a_workflow_with_no_shape_is_not_runnable(self) -> None:
        runnable, reason = handlers._is_runnable({"workflow_shape": None})
        assert runnable is False
        assert "shape" in reason

    def test_a_workflow_with_no_file_path_is_not_runnable(self) -> None:
        runnable, reason = handlers._is_runnable({"workflow_shape": SHAPE, "file_path": None})
        assert runnable is False
        assert "file path" in reason

    def test_a_missing_file_on_disk_is_not_runnable(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        missing = tmp_path / "gone.py"
        monkeypatch.setattr(handlers.WorkflowRegistry, "get_complete_file_path", staticmethod(lambda p: str(p)))

        runnable, reason = handlers._is_runnable({"workflow_shape": SHAPE, "file_path": str(missing)})

        assert runnable is False
        assert "missing from disk" in reason

    def test_a_present_file_with_a_shape_is_runnable(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        present = tmp_path / "here.py"
        present.write_text("# workflow")
        monkeypatch.setattr(handlers.WorkflowRegistry, "get_complete_file_path", staticmethod(lambda p: str(p)))

        runnable, reason = handlers._is_runnable({"workflow_shape": SHAPE, "file_path": str(present)})

        assert runnable is True
        assert reason == ""


class TestGetExecutionState:
    def test_a_running_flow_reports_active_and_involved_nodes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = FakeDispatchEngine(
            {
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                GetFlowStateRequest: GetFlowStateResultSuccess(
                    control_nodes=["C1"], resolving_nodes=["N1"], involved_nodes=["N1", "N2"], result_details="ok"
                ),
                GetWorkflowContextRequest: GetWorkflowContextSuccess(workflow_name="wf1", result_details="ok"),
            }
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_get_execution_state(NukeGetExecutionStateRequest(include_outputs=False))

        assert isinstance(result, NukeGetExecutionStateResultSuccess)
        assert result.running is True
        assert result.active_nodes == ["N1"]
        assert result.involved_nodes == ["N1", "N2"]
        assert result.workflow_id == "wf1"
        assert result.outputs == {}

    def test_include_outputs_reads_the_declared_output_ports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def respond_to_get_value(request: GetParameterValueRequest) -> Any:
            if request.parameter_name == "was_successful":
                return GetParameterValueResultSuccess(
                    input_types=["bool"], type="bool", output_type="bool", value=True, result_details="ok"
                )
            return GetParameterValueResultSuccess(
                input_types=["AudioUrlArtifact"],
                type="AudioUrlArtifact",
                output_type="AudioUrlArtifact",
                value="http://x/audio.mp3",
                result_details="ok",
            )

        engine = FakeDispatchEngine(
            {
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                GetFlowStateRequest: GetFlowStateResultSuccess(
                    control_nodes=[], resolving_nodes=[], involved_nodes=[], result_details="ok"
                ),
                GetWorkflowContextRequest: GetWorkflowContextSuccess(workflow_name="wf1", result_details="ok"),
                ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(
                    workflows={"wf1": {"workflow_shape": SHAPE}}, result_details="ok"
                ),
                GetParameterValueRequest: respond_to_get_value,
            }
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_get_execution_state(NukeGetExecutionStateRequest(include_outputs=True))

        assert isinstance(result, NukeGetExecutionStateResultSuccess)
        assert result.outputs["End Flow"]["was_successful"]["value_type"] == ValueType.BOOLEAN
        assert result.outputs["End Flow"]["mixed_audio"]["value_type"] == ValueType.FILE

    def test_fails_when_no_workflow_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = FakeDispatchEngine(
            {GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name=None, result_details="ok")}
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_get_execution_state(NukeGetExecutionStateRequest())

        assert isinstance(result, NukeGetExecutionStateResultFailure)
        assert len(engine.requests) == 1, "must not ask the engine for flow state with nothing loaded"


class TestCancelExecution:
    def test_cancellation_is_requested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = FakeDispatchEngine(
            {
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                CancelFlowRequest: CancelFlowResultSuccess(result_details="cancelled"),
            }
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_cancel_execution(NukeCancelExecutionRequest())

        assert isinstance(result, NukeCancelExecutionResultSuccess)

    def test_fails_when_no_workflow_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = FakeDispatchEngine(
            {GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name=None, result_details="ok")}
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_cancel_execution(NukeCancelExecutionRequest())

        assert isinstance(result, NukeCancelExecutionResultFailure)
        assert not any(isinstance(request, CancelFlowRequest) for request in engine.requests)

    def test_fails_when_the_engine_refuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = FakeDispatchEngine(
            {
                GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
                CancelFlowRequest: CancelFlowResultFailure(result_details="nothing running"),
            }
        )
        monkeypatch.setattr(handlers, "GriptapeNodes", engine)

        result = handlers.handle_cancel_execution(NukeCancelExecutionRequest())

        assert isinstance(result, NukeCancelExecutionResultFailure)
