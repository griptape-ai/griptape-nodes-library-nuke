"""Tests for the engine facade.

Narrowing and the shared queries are what every verb is built on, so a wrong answer here
is a wrong answer six times over.
"""

from __future__ import annotations

import pytest
from griptape_nodes.retained_mode.events.app_events import (
    GetEngineNameRequest,
    GetEngineNameResultFailure,
    GetEngineVersionRequest,
    GetEngineVersionResultFailure,
)
from griptape_nodes.retained_mode.events.context_events import (
    GetWorkflowContextFailure,
    GetWorkflowContextRequest,
    GetWorkflowContextSuccess,
)
from griptape_nodes.retained_mode.events.execution_events import GetFlowStateRequest, GetFlowStateResultSuccess
from griptape_nodes.retained_mode.events.flow_events import (
    GetTopLevelFlowRequest,
    GetTopLevelFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    ListAllWorkflowsRequest,
    ListAllWorkflowsResultFailure,
    ListAllWorkflowsResultSuccess,
)

from nuke_host_api import engine
from tests.unit.host_api_fakes import ENGINE_NAME, ENGINE_VERSION, IDLE_FLOW, WORKFLOW_TABLE, use_engine

BUSY_FLOW = GetFlowStateResultSuccess(
    control_nodes=["C1"], resolving_nodes=["N1"], involved_nodes=["N1"], result_details="busy"
)

LOADED_FLOW = {GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok")}


class TestRequest:
    def test_a_success_is_narrowed_to_the_expected_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch, {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows={}, result_details="ok")}
        )

        attempt = engine.request(ListAllWorkflowsRequest(), ListAllWorkflowsResultSuccess)

        assert attempt.value is not None
        assert attempt.details == "ok"

    def test_a_refusal_carries_the_engines_own_words(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A handler quotes these inside the failure it words for a host, so they must survive."""
        use_engine(
            monkeypatch, {ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="registry gone")}
        )

        attempt = engine.request(ListAllWorkflowsRequest(), ListAllWorkflowsResultSuccess)

        assert attempt.value is None
        assert attempt.details == "registry gone"


class TestEventTopic:
    """A host cannot derive this, so connect hands it over."""

    def test_a_session_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch)
        assert engine.event_topic() == "sessions/session-abc/response"

    def test_the_engine_id_is_the_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, session_id="")
        assert engine.event_topic() == "engines/engine-xyz/response"

    def test_a_bare_topic_is_the_last_resort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, session_id="", engine_id="")
        assert engine.event_topic() == "response"


class TestEngineVersion:
    def test_the_three_parts_are_joined(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {GetEngineVersionRequest: ENGINE_VERSION})
        assert engine.engine_version() == "0.97.0"

    def test_an_engine_that_will_not_say_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {GetEngineVersionRequest: GetEngineVersionResultFailure(result_details="no")})
        assert engine.engine_version() == "unknown"


class TestEngineId:
    def test_a_set_id_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, engine_id="engine-xyz")
        assert engine.engine_id() == "engine-xyz"

    def test_no_id_is_empty_not_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, engine_id="")
        assert engine.engine_id() == ""


class TestSessionId:
    def test_a_set_session_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, session_id="session-abc")
        assert engine.session_id() == "session-abc"

    def test_a_direct_engine_connection_with_no_session_is_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, session_id="")
        assert engine.session_id() == ""


class TestEngineName:
    def test_the_engines_name_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {GetEngineNameRequest: ENGINE_NAME})
        assert engine.engine_name() == "Engine One"

    def test_an_engine_that_refuses_the_lookup_is_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The engine's own handler fails only on an unexpected exception, never on an unset name."""
        use_engine(
            monkeypatch,
            {GetEngineNameRequest: GetEngineNameResultFailure(error_message="boom", result_details="boom")},
        )
        assert engine.engine_name() == ""


class TestTopLevelFlowName:
    """GetFlowStateRequest and CancelFlowRequest both reject a null flow name."""

    def test_the_loaded_flow_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, LOADED_FLOW)
        assert engine.top_level_flow_name() == "main"

    def test_nothing_loaded_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch, {GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name=None, result_details="ok")}
        )
        assert engine.top_level_flow_name() is None

    def test_a_result_that_is_not_the_success_type_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The engine ships no failure payload for this request today, so any other result stands in.

        Treating an unrecognized answer as "nothing loaded" is what keeps a future failure type
        from reaching a caller as a success it would then read fields off.
        """
        use_engine(monkeypatch, {GetTopLevelFlowRequest: GetWorkflowContextFailure(result_details="unexpected")})
        assert engine.top_level_flow_name() is None


class TestCurrentWorkflowId:
    def test_the_loaded_workflow_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {GetWorkflowContextRequest: GetWorkflowContextSuccess(workflow_name="wf1", result_details="ok")},
        )
        assert engine.current_workflow_id() == "wf1"

    def test_no_context_is_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {GetWorkflowContextRequest: GetWorkflowContextFailure(result_details="none")})
        assert engine.current_workflow_id() == ""


class TestWorkflowEntry:
    def test_a_known_id_returns_its_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows=WORKFLOW_TABLE, result_details="ok")},
        )
        assert engine.workflow_entry("wf1") == WORKFLOW_TABLE["wf1"]

    def test_an_unknown_id_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows=WORKFLOW_TABLE, result_details="ok")},
        )
        assert engine.workflow_entry("ghost") is None

    def test_an_unreadable_registry_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="gone")})
        assert engine.workflow_entry("wf1") is None

    def test_a_malformed_entry_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {
                ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(
                    workflows={"wf1": "not a dict"}, result_details="ok"
                )
            },
        )
        assert engine.workflow_entry("wf1") is None


class TestLookupWorkflow:
    """An unreadable registry is worth retrying and an unknown id never is.

    Two verbs word different failures for the two, so the split lives here rather than in
    each of them.
    """

    def test_a_known_id_returns_its_entry_from_a_readable_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows=WORKFLOW_TABLE, result_details="ok")},
        )
        found = engine.lookup_workflow("wf1")
        assert found.entry == WORKFLOW_TABLE["wf1"]
        assert found.registry_readable is True

    def test_an_unknown_id_in_a_readable_registry_is_not_an_unreadable_registry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        use_engine(
            monkeypatch,
            {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows=WORKFLOW_TABLE, result_details="ok")},
        )
        found = engine.lookup_workflow("ghost")
        assert found.entry is None
        assert found.registry_readable is True

    def test_an_unreadable_registry_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="gone")})
        found = engine.lookup_workflow("wf1")
        assert found.entry is None
        assert found.registry_readable is False

    def test_a_malformed_entry_reads_as_an_unknown_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(
            monkeypatch,
            {
                ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(
                    workflows={"wf1": "not a dict"}, result_details="ok"
                )
            },
        )
        found = engine.lookup_workflow("wf1")
        assert found.entry is None
        assert found.registry_readable is True


class TestIsRunning:
    """One predicate for the execute guard and the state report, so they cannot disagree."""

    def test_resolving_or_control_nodes_mean_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {**LOADED_FLOW, GetFlowStateRequest: BUSY_FLOW})
        assert engine.is_running() is True

    def test_an_idle_flow_is_not_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {**LOADED_FLOW, GetFlowStateRequest: IDLE_FLOW})
        assert engine.is_running() is False

    def test_nothing_loaded_is_not_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = use_engine(
            monkeypatch, {GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name=None, result_details="ok")}
        )

        assert engine.is_running() is False
        assert not any(isinstance(request, GetFlowStateRequest) for request in fake.requests), (
            "must not ask for flow state with nothing loaded"
        )
