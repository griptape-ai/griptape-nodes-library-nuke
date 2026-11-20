from __future__ import annotations

from nuke_host_api import run_outcome
from nuke_host_api.protocol import ExecutionState


def test_a_start_failure_outranks_a_cancel_and_a_node_error() -> None:
    run_outcome.begin_host_run(frozenset())
    run_outcome.note_node_error("node broke")
    run_outcome.on_cancelled("stopped", "wf1")

    verdict = run_outcome.conclude("start refused", "wf1")

    assert (verdict.state, verdict.detail) == (ExecutionState.FAILED, "start refused")


def test_a_cancel_outranks_a_node_error() -> None:
    run_outcome.note_node_error("node broke")

    verdict = run_outcome.on_cancelled("stopped", "wf1")

    assert verdict is not None
    assert verdict.state == ExecutionState.CANCELLED


def test_the_first_node_error_is_the_reason() -> None:
    run_outcome.note_node_error("first")
    run_outcome.note_node_error("second")

    assert run_outcome.conclude(None, "wf1").detail == "first"


def test_an_editor_run_concludes_on_resolve_at_its_terminal_node() -> None:
    verdict = run_outcome.on_resolved("End Flow", "wf1")

    assert verdict is not None
    assert (verdict.state, verdict.terminal_node) == (ExecutionState.SUCCEEDED, "End Flow")


def test_a_host_run_does_not_conclude_on_engine_events() -> None:
    run_outcome.begin_host_run(frozenset())

    assert run_outcome.on_resolved("End Flow", "wf1") is None
    assert run_outcome.on_cancelled("stopped", "wf1") is None
    assert run_outcome.conclude(None, "wf1").state == ExecutionState.CANCELLED


def test_concluding_forgets_the_run_but_remembers_the_verdict() -> None:
    run_outcome.begin_host_run(frozenset())
    run_outcome.note_node_error("node broke")
    verdict = run_outcome.conclude(None, "wf1")

    assert run_outcome.host_run() is False
    assert run_outcome.last("wf1") == verdict
    assert run_outcome.conclude(None, "wf1").state == ExecutionState.SUCCEEDED


def test_a_verdict_is_not_reported_for_another_workflow() -> None:
    run_outcome.conclude("broke", "wf1")

    assert run_outcome.last("wf2") is None


def test_a_host_run_that_resolves_no_end_node_fails_naming_where_it_stopped() -> None:
    run_outcome.begin_host_run(frozenset({"End Flow"}))
    run_outcome.note_node_resolved("Subflow")
    run_outcome.on_resolved("Subflow", "wf1")

    verdict = run_outcome.conclude(None, "wf1")

    assert verdict.state == ExecutionState.FAILED
    assert verdict.detail == "The run stopped at 'Subflow' before 'End Flow' ran, so the workflow produced no outputs."


def test_a_host_run_succeeds_once_any_end_node_resolves() -> None:
    run_outcome.begin_host_run(frozenset({"End A", "End B"}))
    run_outcome.note_node_resolved("End B")

    assert run_outcome.conclude(None, "wf1").state == ExecutionState.SUCCEEDED


def test_a_node_error_outranks_a_missing_end_node() -> None:
    run_outcome.begin_host_run(frozenset({"End Flow"}))
    run_outcome.note_node_error("node broke")

    assert run_outcome.conclude(None, "wf1").detail == "node broke"


def test_an_end_node_resolved_before_the_run_does_not_count() -> None:
    run_outcome.note_node_resolved("End Flow")
    run_outcome.begin_host_run(frozenset({"End Flow"}))

    assert run_outcome.conclude(None, "wf1").state == ExecutionState.FAILED


def test_a_host_run_with_no_declared_end_node_is_not_held_to_one() -> None:
    run_outcome.begin_host_run(frozenset())

    assert run_outcome.conclude(None, "wf1").state == ExecutionState.SUCCEEDED
