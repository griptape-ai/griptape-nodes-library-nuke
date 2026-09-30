from __future__ import annotations

from nuke_host_api import run_outcome
from nuke_host_api.protocol import ExecutionState


def test_a_start_failure_outranks_a_cancel_and_a_node_error() -> None:
    run_outcome.begin_host_run()
    run_outcome.note_node_error("node broke")
    run_outcome.note_cancelled("stopped")

    verdict = run_outcome.conclude("start refused")

    assert (verdict.state, verdict.detail) == (ExecutionState.FAILED, "start refused")


def test_a_cancel_outranks_a_node_error() -> None:
    run_outcome.note_node_error("node broke")
    run_outcome.note_cancelled("stopped")

    assert run_outcome.conclude().state == ExecutionState.CANCELLED


def test_the_first_node_error_is_the_reason() -> None:
    run_outcome.note_node_error("first")
    run_outcome.note_node_error("second")

    assert run_outcome.conclude().detail == "first"


def test_a_run_with_nothing_noted_succeeds_on_its_terminal_node() -> None:
    run_outcome.note_resolved("End Flow")

    verdict = run_outcome.conclude()

    assert (verdict.state, verdict.terminal_node) == (ExecutionState.SUCCEEDED, "End Flow")


def test_concluding_forgets_the_run_but_remembers_the_verdict() -> None:
    run_outcome.begin_host_run()
    run_outcome.note_node_error("node broke")
    verdict = run_outcome.conclude()

    assert run_outcome.host_run() is False
    assert run_outcome.last() == verdict
    assert run_outcome.conclude().state == ExecutionState.SUCCEEDED
