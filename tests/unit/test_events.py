"""Tests for the payload dataclasses that handler tests exercise only through isinstance."""

from __future__ import annotations

import dataclasses

import pytest

from nuke_host_api import events

# These four answer a verb with no payload of their own, so their emptiness is the contract.
FIELDLESS_RESULT_CLASSES = [
    events.NukeGetParameterValuesResultFailure,
    events.NukeListWorkflowsResultFailure,
    events.NukeCancelExecutionResultSuccess,
    events.NukeCancelExecutionResultFailure,
]


@pytest.mark.parametrize("cls", FIELDLESS_RESULT_CLASSES, ids=lambda cls: cls.__name__)
def test_a_result_documented_as_carrying_no_payload_declares_no_own_fields(cls: type) -> None:
    """A field added here would extend the wire contract without any doc or test saying so."""
    own_fields = {f.name for f in dataclasses.fields(cls)}
    assert own_fields <= {"result_details", "exception", "altered_workflow_state"}
