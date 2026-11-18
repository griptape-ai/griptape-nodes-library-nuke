"""Tests for the load verb.

Loading closes the host's previous workflow, so most of these assert what the handler does
*not* do: a request that cannot succeed must not reach ``RunWorkflowFromRegistryRequest``,
because the graph the host had loaded is gone the moment it does.
"""

from __future__ import annotations

from typing import Any

import pytest
from griptape_nodes.retained_mode.events.context_events import OpenWorkflowRequest, OpenWorkflowResultFailure
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
)

from nuke_host_api import engine, flow_run, loaded_workflow, run_outcome
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
    return any(isinstance(request, OpenWorkflowRequest) for request in engine.requests)


class TestLoadWorkflow:
    async def test_a_workflow_id_is_opened(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, load_responses())

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert result.workflow_id == "wf1"
        assert result.name == "WF One"
        opened = next(r for r in engine.requests if isinstance(r, OpenWorkflowRequest))
        assert opened.workflow_name == "wf1"

    async def test_a_load_forgets_the_previous_graphs_verdict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reloading the same id still discards the graph the verdict described."""
        run_outcome.conclude("wf1 broke", "wf1")
        use_engine(monkeypatch, load_responses())

        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert run_outcome.last("wf1") is None

    async def test_an_execute_cannot_start_while_a_load_is_in_flight(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, load_responses())
        held: list[bool] = []
        lookup = engine.lookup_workflow

        async def spy(workflow_id: str) -> engine.WorkflowLookup:
            with flow_run.reserve() as reserved:
                held.append(not reserved)
            return await lookup(workflow_id)

        monkeypatch.setattr(engine, "lookup_workflow", spy)

        await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert held == [True]
        assert flow_run.pending() is False

    async def test_declared_parameters_match_what_describe_publishes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A host must not have to call describe as well, nor learn a second descriptor shape."""
        use_engine(monkeypatch, load_responses())

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert {declared["parameter"] for declared in result.inputs} == {"topic", "plate"}
        assert {declared["parameter"] for declared in result.outputs} == {"was_successful", "mixed_audio"}
        assert set(result.inputs[0]) == {
            "node",
            "parameter",
            "name",
            "type",
            "is_list",
            "is_sequence",
            "default_value",
            "choices",
            "file_format",
            "tooltip",
            "settable",
            "hidden",
        }

    async def test_current_values_come_back_for_both_sides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole point of the verb: knobs can be built and initialized from one reply."""
        use_engine(monkeypatch, load_responses())

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert result.input_values["Start Flow"]["topic"]["value_type"] == ValueType.TEXT
        assert result.output_values["End Flow"]["was_successful"]["value_type"] == ValueType.BOOL
        assert result.unavailable == []

    async def test_a_declared_default_is_a_value_while_a_live_value_is_a_descriptor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        use_engine(monkeypatch, load_responses())

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        keys = {"value_type", "value", "engine_type"}
        assert set(result.input_values["Start Flow"]["topic"]) == keys
        topic = next(declared for declared in result.inputs if declared["parameter"] == "topic")
        assert topic["default_value"] == "a quiet harbour at dusk"

    async def test_control_parameters_reach_neither_the_declarations_nor_the_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        use_engine(monkeypatch, load_responses())

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert "exec_out" not in {declared["parameter"] for declared in result.inputs}
        assert "exec_out" not in result.input_values.get("Start Flow", {})
        assert "exec_in" not in result.output_values.get("End Flow", {})

    async def test_a_file_path_is_imported_and_the_resolved_id_is_returned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A host that picked a file has no id to send, so the reply is where it learns one."""
        engine = use_engine(
            monkeypatch,
            load_responses(
                {ImportWorkflowRequest: ImportWorkflowResultSuccess(workflow_name="wf1", result_details="imported")}
            ),
        )

        result = await handle_load_workflow(NukeLoadWorkflowRequest(file_path="/shots/sq010/comp.py"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert result.workflow_id == "wf1"
        imported = next(r for r in engine.requests if isinstance(r, ImportWorkflowRequest))
        assert imported.file_path == "/shots/sq010/comp.py"

    async def test_a_file_the_engine_cannot_import_is_refused_before_anything_is_cleared(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = use_engine(
            monkeypatch,
            load_responses({ImportWorkflowRequest: ImportWorkflowResultFailure(result_details="not a workflow file")}),
        )

        result = await handle_load_workflow(NukeLoadWorkflowRequest(file_path="/tmp/notes.txt"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert "not a workflow file" in str(result.result_details)
        assert not _loaded(engine)

    async def test_both_a_workflow_id_and_a_file_path_is_refused_without_touching_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """They can name different workflows, and guessing which one the host meant is worse."""
        engine = use_engine(monkeypatch, load_responses())

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1", file_path="/shots/other.py"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert engine.requests == []

    async def test_an_empty_request_is_refused_without_touching_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = use_engine(monkeypatch, load_responses())

        result = await handle_load_workflow(NukeLoadWorkflowRequest())

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert engine.requests == []

    async def test_refuses_while_the_hosts_workflow_is_executing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Loading replaces the workflow the host's run belongs to, and the host would lose track of it."""
        engine = use_engine(monkeypatch, load_responses({GetFlowStateRequest: BUSY_FLOW}), loaded="wf0")

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.engine_state_cleared is False
        assert not _loaded(engine)

    async def test_another_workflows_run_does_not_block_a_load(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With nothing loaded there is no host run to wait for, whatever an editor tab is running."""
        engine = use_engine(monkeypatch, load_responses({GetFlowStateRequest: BUSY_FLOW}))
        engine.open_workflows.open("editor-tab")

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)

    async def test_an_unknown_id_is_refused_before_anything_is_opened(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The registry is read first for exactly this reason."""
        engine = use_engine(monkeypatch, load_responses())

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="ghost"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.workflow_id == "ghost"
        assert not _loaded(engine)

    async def test_an_unreadable_registry_is_a_different_answer_than_an_unknown_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One is worth retrying, the other never is."""
        engine = use_engine(
            monkeypatch, load_responses({ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="down")})
        )

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert "registry" in str(result.result_details)
        assert not _loaded(engine)

    async def test_the_engines_own_reason_for_refusing_to_load_reaches_the_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A host cannot see the engine's result, so a refusal it never quotes is lost."""
        engine = use_engine(
            monkeypatch,
            load_responses(
                {OpenWorkflowRequest: OpenWorkflowResultFailure(result_details="the workflow file is missing")}
            ),
        )

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.workflow_id == "wf1"
        assert "the workflow file is missing" in str(result.result_details)
        assert not any(isinstance(r, GetParameterValueRequest) for r in engine.requests), (
            "must not read values off a graph it never loaded"
        )

    async def test_a_load_the_engine_refuses_keeps_the_previous_workflow_loaded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The new workflow is opened before the previous one is closed, so a failed open costs nothing."""
        engine = use_engine(
            monkeypatch,
            load_responses({OpenWorkflowRequest: OpenWorkflowResultFailure(result_details="library missing")}),
            loaded="wf0",
        )

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.engine_state_cleared is False
        assert "library missing" in str(result.result_details)
        assert engine.open_workflows.find("wf0-open") is not None
        loaded = loaded_workflow.current()
        assert loaded is not None
        assert loaded.name == "wf0"

    @pytest.mark.parametrize(
        ("request_payload", "overrides"),
        [
            (NukeLoadWorkflowRequest(workflow_id="ghost"), {}),
            (NukeLoadWorkflowRequest(), {}),
            (NukeLoadWorkflowRequest(workflow_id="wf1", file_path="/shots/other.py"), {}),
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
    async def test_a_refusal_decided_before_the_engine_load_reports_nothing_cleared(
        self,
        monkeypatch: pytest.MonkeyPatch,
        request_payload: NukeLoadWorkflowRequest,
        overrides: dict[type, Any],
    ) -> None:
        """The flag is a host's recovery signal, so it must be false for every cheap refusal."""
        use_engine(monkeypatch, load_responses(overrides))

        result = await handle_load_workflow(request_payload)

        assert isinstance(result, NukeLoadWorkflowResultFailure)
        assert result.engine_state_cleared is False

    async def test_a_clean_load_costs_two_engine_requests_plus_one_per_declared_parameter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The cost scales with the workflow, which is why no fixed number is documented."""
        engine = use_engine(monkeypatch, load_responses())

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        declared = len(result.inputs) + len(result.outputs)
        assert len(engine.requests) == 2 + declared
        assert sum(isinstance(r, GetParameterValueRequest) for r in engine.requests) == declared

    async def test_a_file_path_load_costs_one_engine_request_more(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, load_responses())

        result = await handle_load_workflow(NukeLoadWorkflowRequest(file_path="/shots/sq010/comp.py"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert len(engine.requests) == 3 + len(result.inputs) + len(result.outputs)

    async def test_a_parameter_the_engine_will_not_answer_for_is_reported_not_omitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same rule as the bulk read verb, because both go through one reader."""

        def respond(request: GetParameterValueRequest) -> Any:
            if request.parameter_name == "topic":
                return GetParameterValueResultFailure(result_details="node was deleted mid-read")
            return respond_to_get_value(request)

        use_engine(monkeypatch, load_responses({GetParameterValueRequest: respond}))

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="wf1"))

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

    async def test_a_workflow_with_no_declared_shape_loads_and_reports_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The engine sends workflow_shape as null for some workflows. It is still loadable."""
        table = {**WORKFLOW_TABLE, "shapeless": {"name": "Shapeless"}}
        engine = use_engine(
            monkeypatch,
            load_responses(
                {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows=table, result_details="ok")}
            ),
        )

        result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id="shapeless"))

        assert isinstance(result, NukeLoadWorkflowResultSuccess)
        assert result.inputs == []
        assert result.input_values == {}
        assert result.unavailable == []
        assert _loaded(engine)
