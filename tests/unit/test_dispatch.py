"""Tests for the handler calling convention."""

from __future__ import annotations

import pytest
from griptape_nodes.retained_mode.events.base_events import RequestPayload, ResultPayload

from nuke_host_api.dispatch import failure, verb
from nuke_host_api.events import (
    NukeConnectRequest,
    NukeDescribeWorkflowResultFailure,
    NukeListWorkflowsRequest,
    NukeListWorkflowsResultFailure,
)


class TestVerb:
    def test_the_declared_request_type_reaches_the_body(self) -> None:
        @verb(NukeConnectRequest)
        def handler(request: NukeConnectRequest) -> ResultPayload:
            return NukeListWorkflowsResultFailure(result_details=request.client_name)

        result = handler(NukeConnectRequest(client_name="Nuke 16.0v7"))

        assert str(result.result_details) == "Nuke 16.0v7"

    def test_a_wrong_request_type_raises(self) -> None:
        """Guards against a registry mix-up routing the wrong payload to a handler."""

        @verb(NukeConnectRequest)
        def handler(request: NukeConnectRequest) -> ResultPayload:  # noqa: ARG001
            msg = "must not be reached"
            raise AssertionError(msg)

        with pytest.raises(TypeError, match="Expected NukeConnectRequest, got NukeListWorkflowsRequest"):
            handler(NukeListWorkflowsRequest())

    def test_the_class_itself_is_not_an_instance(self) -> None:
        """The engine hands over instances; a class arriving here means a caller passed the type."""

        @verb(NukeConnectRequest)
        def handler(request: NukeConnectRequest) -> ResultPayload:  # noqa: ARG001
            msg = "must not be reached"
            raise AssertionError(msg)

        with pytest.raises(TypeError):
            handler(NukeConnectRequest)  # type: ignore[arg-type]

    def test_the_handler_keeps_its_identity(self) -> None:
        """The engine logs these by name, so the wrapper must not rename them."""

        @verb(NukeConnectRequest)
        def handle_something(request: RequestPayload) -> ResultPayload:  # noqa: ARG001
            return NukeListWorkflowsResultFailure(result_details="")

        assert handle_something.__name__ == "handle_something"


class TestFailure:
    def test_the_wording_is_attempted_then_because(self) -> None:
        result = failure(
            NukeListWorkflowsResultFailure,
            attempted="to list workflows for a host",
            because="the engine could not read the workflow registry.",
        )

        assert str(result.result_details) == (
            "Attempted to list workflows for a host. Failed because the engine could not read the workflow registry."
        )

    def test_the_exception_carries_the_same_text(self) -> None:
        """A host reading either one must not see two accounts of the same refusal."""
        result = failure(NukeListWorkflowsResultFailure, attempted="to do a thing", because="a reason.")

        assert str(result.exception) == str(result.result_details)

    def test_the_error_type_is_the_callers_choice(self) -> None:
        result = failure(
            NukeDescribeWorkflowResultFailure,
            attempted="to describe workflow 'ghost'",
            because="no workflow with that name is registered.",
            error=KeyError,
            workflow_id="ghost",
        )

        assert isinstance(result.exception, KeyError)

    def test_payload_specific_fields_are_forwarded(self) -> None:
        result = failure(
            NukeDescribeWorkflowResultFailure,
            attempted="to describe workflow 'ghost'",
            because="no workflow with that name is registered.",
            workflow_id="ghost",
        )

        assert result.workflow_id == "ghost"
