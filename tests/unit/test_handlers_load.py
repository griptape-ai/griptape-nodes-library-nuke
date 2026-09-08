"""Tests for the load verb.

Loading clears all object state, so most of these assert what the handler does *not* do: a
request that cannot succeed must not reach ``RunWorkflowFromRegistryRequest``, because
whatever the engine had loaded before, including a graph an editor user has open, is gone the
moment it does.
"""

from __future__ import annotations

from typing import Any

import pytest
from griptape_nodes.retained_mode.events.execution_events import (
    GetFlowStateRequest,
    GetFlowStateResultSuccess,
)
from griptape_nodes.retained_mode.events.parameter_events import (
    GetParameterValueRequest,
    GetParameterValueResultFailure,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    ImportWorkflowRequest,
    ImportWorkflowResultFailure,
    ImportWorkflowResultSuccess,
    ListAllWorkflowsRequest,
    ListAllWorkflowsResultFailure,
    ListAllWorkflowsResultSuccess,
    RunWorkflowFromRegistryRequest,
    RunWorkflowFromRegistryResultFailure,
)

from nuke_host_api.events import (
    NukeLoadWorkflowRequest,
    NukeLoadWorkflowResultFailure,
    NukeLoadWorkflowResultSuccess,
)
from nuke_host_api.handlers import handle_load_workflow
from nuke_host_api.protocol import ParameterSection, ValueType
from tests.unit.host_api_fakes import WORKFLOW_TABLE, load_responses, respond_to_get_value, use_engine

BUSY_FLOW = GetFlowStateResultSuccess(
    control_nodes=["C1"], resolving_nodes=["N1"], involved_nodes=["N1"], result_details="busy"
)


def _loaded(engine: Any) -> bool:
    return any(isinstance(request, RunWorkflowFromRegistryRequest) for request in engine.requests)


class TestLoadWorkflow:
    def test_a_workflow_id_is_loaded_with_a_clean_slate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, load_responses())

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert result.workflow_id == "wf1"
        assert result.name == "WF One"
        load = next(r for r in engine.requests if isinstance(r, RunWorkflowFromRegistryRequest))
        assert load.workflow_name == "wf1"
        assert load.run_with_clean_slate is True

    def test_declared_parameters_match_what_describe_publishes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A host must not have to call describe as well, nor learn a second descriptor shape."""
        use_engine(monkeypatch, load_responses())

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert {declared["parameter"] for declared in result.inputs} == {"topic", "plate"}
        assert {declared["parameter"] for declared in result.outputs} == {"was_successful", "mixed_audio"}
        assert set(result.inputs[0]) == {"node", "parameter", "name", "type", "default", "tooltip", "settable"}

    def test_current_values_come_back_for_both_sides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole point of the verb: knobs can be built and initialized from one reply."""
        use_engine(monkeypatch, load_responses())

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert result.input_values["Start Flow"]["topic"]["value_type"] == ValueType.TEXT
        assert result.output_values["End Flow"]["was_successful"]["value_type"] == ValueType.BOOL
        assert result.unavailable == []

    def test_values_use_the_same_descriptor_shape_as_a_declared_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, load_responses())

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        keys = {"value_type", "sources", "colorspace", "engine_type"}
        assert set(result.input_values["Start Flow"]["topic"]) == keys
        assert set(result.inputs[0]["default"]) == keys

    def test_control_parameters_reach_neither_the_declarations_nor_the_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        use_engine(monkeypatch, load_responses())

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert "exec_out" not in {declared["parameter"] for declared in result.inputs}
        assert "exec_out" not in result.input_values.get("Start Flow", {})
        assert "exec_in" not in result.output_values.get("End Flow", {})

    def test_a_file_path_is_imported_and_the_resolved_id_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A host that picked a file has no id to send, so the reply is where it learns one."""
        engine = use_engine(
            monkeypatch,
            load_responses(
                {ImportWorkflowRequest: ImportWorkflowResultSuccess(workflow_name="wf1", result_details="imported")}
            ),
        )

        result = handle_load_workflow(NukeLoadWorkflowRequest(file_path="/shots/sq010/comp.py"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert result.workflow_id == "wf1"
        imported = next(r for r in engine.requests if isinstance(r, ImportWorkflowRequest))
        assert imported.file_path == "/shots/sq010/comp.py"

    def test_a_file_the_engine_cannot_import_is_refused_before_anything_is_cleared(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = use_engine(
            monkeypatch,
            load_responses({ImportWorkflowRequest: ImportWorkflowResultFailure(result_details="not a workflow file")}),
        )

        result = handle_load_workflow(NukeLoadWorkflowRequest(file_path="/tmp/notes.txt"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert "not a workflow file" in str(result.result_details)
        assert not _loaded(engine)

    def test_both_a_workflow_id_and_a_file_path_is_refused_without_touching_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """They can name different workflows, and guessing which one the host meant is worse."""
        engine = use_engine(monkeypatch, load_responses())

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1", file_path="/shots/other.py"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert engine.requests == []

    def test_an_empty_request_is_refused_without_touching_the_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, load_responses())

        result = handle_load_workflow(NukeLoadWorkflowRequest())

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert engine.requests == []

    def test_refuses_while_the_engine_is_executing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Loading discards the running graph, and the host would still be told it succeeded."""
        engine = use_engine(monkeypatch, load_responses({GetFlowStateRequest: BUSY_FLOW}))

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert not _loaded(engine)

    def test_an_unknown_id_is_refused_before_the_engine_state_is_cleared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The registry is read first for exactly this reason."""
        engine = use_engine(monkeypatch, load_responses())

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="ghost"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.workflow_id == "ghost"
        assert not _loaded(engine)

    def test_an_unreadable_registry_is_a_different_answer_than_an_unknown_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One is worth retrying, the other never is."""
        engine = use_engine(
            monkeypatch, load_responses({ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="down")})
        )

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert "registry" in str(result.result_details)
        assert not _loaded(engine)

    def test_the_engines_own_reason_for_refusing_to_load_reaches_the_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A host cannot see the engine's result, so a refusal it never quotes is lost."""
        engine = use_engine(
            monkeypatch,
            load_responses(
                {
                    RunWorkflowFromRegistryRequest: RunWorkflowFromRegistryResultFailure(
                        result_details="the workflow file is missing"
                    )
                }
            ),
        )

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.workflow_id == "wf1"
        assert "the workflow file is missing" in str(result.result_details)
        assert not any(isinstance(r, GetParameterValueRequest) for r in engine.requests), (
            "must not read values off a graph it never loaded"
        )

    def test_a_load_the_engine_refuses_reports_that_the_previous_graph_is_already_gone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The engine clears all object state before it builds the graph, so this failure costs.

        A host that read the refusal as "nothing changed" would keep showing knobs for a graph
        the engine no longer holds, and the artist whose comp was discarded gets no signal.
        """
        use_engine(
            monkeypatch,
            load_responses(
                {RunWorkflowFromRegistryRequest: RunWorkflowFromRegistryResultFailure(result_details="library missing")}
            ),
        )

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.engine_state_cleared is True
        assert "cleared" in str(result.result_details)

    @pytest.mark.parametrize(
        ("request_payload", "overrides"),
        [
            (NukeLoadWorkflowRequest(workflow_id="ghost"), {}),
            (NukeLoadWorkflowRequest(), {}),
            (NukeLoadWorkflowRequest(workflow_id="wf1", file_path="/shots/other.py"), {}),
            (NukeLoadWorkflowRequest(workflow_id="wf1"), {GetFlowStateRequest: BUSY_FLOW}),
            (
                NukeLoadWorkflowRequest(file_path="/tmp/notes.txt"),
                {ImportWorkflowRequest: ImportWorkflowResultFailure(result_details="not a workflow file")},
            ),
            (
                NukeLoadWorkflowRequest(workflow_id="wf1"),
                {ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="down")},
            ),
        ],
    )
    def test_a_refusal_decided_before_the_engine_load_reports_nothing_cleared(
        self,
        monkeypatch: pytest.MonkeyPatch,
        request_payload: NukeLoadWorkflowRequest,
        overrides: dict[type, Any],
    ) -> None:
        """The flag is a host's recovery signal, so it must be false for every cheap refusal."""
        use_engine(monkeypatch, load_responses(overrides))

        result = handle_load_workflow(request_payload)

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.engine_state_cleared is False

    def test_a_clean_load_costs_four_engine_requests_plus_one_per_declared_parameter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The cost scales with the workflow, which is why no fixed number is documented."""
        engine = use_engine(monkeypatch, load_responses())

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        declared = len(result.inputs) + len(result.outputs)
        assert len(engine.requests) == 4 + declared
        assert sum(isinstance(r, GetParameterValueRequest) for r in engine.requests) == declared

    def test_a_file_path_load_costs_one_engine_request_more(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, load_responses())

        result = handle_load_workflow(NukeLoadWorkflowRequest(file_path="/shots/sq010/comp.py"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert len(engine.requests) == 5 + len(result.inputs) + len(result.outputs)

    def test_a_parameter_the_engine_will_not_answer_for_is_reported_not_omitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same rule as the bulk read verb, because both go through one reader."""

        def respond(request: GetParameterValueRequest) -> Any:
            if request.parameter_name == "topic":
                return GetParameterValueResultFailure(result_details="node was deleted mid-read")
            return respond_to_get_value(request)

        use_engine(monkeypatch, load_responses({GetParameterValueRequest: respond}))

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert "topic" not in result.input_values.get("Start Flow", {})
        assert result.unavailable == [
            {
                "section": ParameterSection.INPUTS,
                "node": "Start Flow",
                "parameter": "topic",
                "reason": "node was deleted mid-read",
            }
        ]
        assert {declared["parameter"] for declared in result.inputs} == {"topic", "plate"}, (
            "an unreadable value must not remove the parameter's declaration"
        )

    def test_a_workflow_with_no_declared_shape_loads_and_reports_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The engine sends workflow_shape as null for some workflows. It is still loadable."""
        table = {**WORKFLOW_TABLE, "shapeless": {"name": "Shapeless"}}
        engine = use_engine(
            monkeypatch,
            load_responses(
                {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows=table, result_details="ok")}
            ),
        )

        result = handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="shapeless"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert result.inputs == []
        assert result.input_values == {}
        assert result.unavailable == []
        assert _loaded(engine)
