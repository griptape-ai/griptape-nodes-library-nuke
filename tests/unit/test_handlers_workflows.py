"""Tests for the workflow discovery verbs."""

from __future__ import annotations

import pytest
from griptape_nodes.retained_mode.events.workflow_events import (
    ListAllWorkflowsRequest,
    ListAllWorkflowsResultFailure,
    ListAllWorkflowsResultSuccess,
)

from nuke_host_api import shape
from nuke_host_api.events import (
    NukeDescribeWorkflowRequest,
    NukeDescribeWorkflowResultFailure,
    NukeDescribeWorkflowResultSuccess,
    NukeListWorkflowsRequest,
    NukeListWorkflowsResultFailure,
    NukeListWorkflowsResultSuccess,
)
from nuke_host_api.handlers import handle_describe_workflow, handle_list_workflows
from nuke_host_api.protocol import ValueType
from tests.unit.host_api_fakes import SHAPE, WORKFLOW_TABLE, use_engine


def _registry(table: dict) -> dict[type, object]:
    return {ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows=table, result_details="ok")}


UNREADABLE_REGISTRY = {ListAllWorkflowsRequest: ListAllWorkflowsResultFailure(result_details="registry unavailable")}


class TestListWorkflows:
    def test_lists_every_workflow_with_its_runnable_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shape, "is_runnable", lambda entry: (entry["id"] == "runnable_one", "not on disk"))
        table = {
            "runnable_one": {"id": "runnable_one", "name": "Runnable", "description": "d1"},
            "broken_one": {"id": "broken_one", "name": "Broken", "description": "d2"},
        }
        use_engine(monkeypatch, _registry(table))

        result = handle_list_workflows(NukeListWorkflowsRequest(runnable_only=False))

        assert isinstance(result, NukeListWorkflowsResultSuccess)
        assert {workflow["id"] for workflow in result.workflows} == {"runnable_one", "broken_one"}

    def test_runnable_only_filters_out_unrunnable_workflows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shape, "is_runnable", lambda entry: (entry["id"] == "runnable_one", "not on disk"))
        use_engine(monkeypatch, _registry({"runnable_one": {"id": "runnable_one"}, "broken_one": {"id": "broken_one"}}))

        result = handle_list_workflows(NukeListWorkflowsRequest(runnable_only=True))

        assert isinstance(result, NukeListWorkflowsResultSuccess)
        assert {workflow["id"] for workflow in result.workflows} == {"runnable_one"}

    def test_a_registry_read_failure_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, UNREADABLE_REGISTRY)

        result = handle_list_workflows(NukeListWorkflowsRequest())

        assert isinstance(result, NukeListWorkflowsResultFailure)


class TestDescribeWorkflow:
    def test_describes_inputs_and_outputs_from_the_workflow_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, _registry(WORKFLOW_TABLE))

        result = handle_describe_workflow(NukeDescribeWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeDescribeWorkflowResultSuccess)
        assert {port["parameter"] for port in result.inputs} == {"topic", "plate"}
        assert {port["parameter"] for port in result.outputs} == {"was_successful", "mixed_audio"}

    def test_ports_carry_the_authors_default_its_help_text_and_whether_it_may_be_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A host builds knobs from this, so a port with no default has nothing to initialize to.

        The default arrives as a normalized descriptor rather than a raw engine value, so a
        port's default and its live value are the same shape.
        """
        use_engine(monkeypatch, _registry(WORKFLOW_TABLE))

        result = handle_describe_workflow(NukeDescribeWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeDescribeWorkflowResultSuccess)
        ports = {port["parameter"]: port for port in result.inputs}

        assert ports["topic"]["default"]["value_type"] == ValueType.TEXT
        assert ports["topic"]["tooltip"] == "What the shot is about."
        assert ports["topic"]["settable"] is True

        assert ports["plate"]["default"]["value_type"] == ValueType.NULL
        assert ports["plate"]["settable"] is False

    def test_a_port_the_engine_gave_no_metadata_for_still_describes_completely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Older workflow_shape entries carry only a type, and every field must still be present.

        A host indexes these keys unconditionally, so an absent one is a crash, not a default.
        """
        use_engine(monkeypatch, _registry(WORKFLOW_TABLE))

        result = handle_describe_workflow(NukeDescribeWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeDescribeWorkflowResultSuccess)
        bare = next(port for port in result.outputs if port["parameter"] == "was_successful")
        assert bare["default"]["value_type"] == ValueType.NULL
        assert bare["tooltip"] == ""
        assert bare["settable"] is True

    def test_an_unknown_workflow_id_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, _registry({}))

        result = handle_describe_workflow(NukeDescribeWorkflowRequest(workflow_id="ghost"))

        assert isinstance(result, NukeDescribeWorkflowResultFailure)
        assert result.workflow_id == "ghost"

    def test_an_unknown_id_and_an_unreadable_registry_are_different_answers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One is worth a retry and the other never is, so the wording must separate them."""
        use_engine(monkeypatch, _registry({}))
        unknown = handle_describe_workflow(NukeDescribeWorkflowRequest(workflow_id="ghost"))

        use_engine(monkeypatch, UNREADABLE_REGISTRY)
        unreadable = handle_describe_workflow(NukeDescribeWorkflowRequest(workflow_id="ghost"))

        assert isinstance(unknown, NukeDescribeWorkflowResultFailure)
        assert isinstance(unreadable, NukeDescribeWorkflowResultFailure)
        assert "no workflow with that name is registered" in str(unknown.result_details)
        assert "could not read the workflow registry" in str(unreadable.result_details)

    def test_a_registry_read_failure_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, UNREADABLE_REGISTRY)

        result = handle_describe_workflow(NukeDescribeWorkflowRequest(workflow_id="wf1"))

        assert isinstance(result, NukeDescribeWorkflowResultFailure)


def test_describe_lists_the_same_ports_execute_will_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host sets what describe published, so the two must be built from one projection."""
    use_engine(monkeypatch, _registry(WORKFLOW_TABLE))

    result = handle_describe_workflow(NukeDescribeWorkflowRequest(workflow_id="wf1"))

    assert isinstance(result, NukeDescribeWorkflowResultSuccess)
    described = {(port["node"], port["parameter"]) for port in result.inputs}
    assert described == shape.input_port_ids({"workflow_shape": SHAPE})
