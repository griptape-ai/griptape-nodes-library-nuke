from __future__ import annotations

import inspect

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
    async def test_the_declared_request_type_reaches_the_body(self) -> None:
        @verb(NukeConnectRequest)
        async def handler(request: NukeConnectRequest) -> ResultPayload:
            return NukeListWorkflowsResultFailure(result_details=request.client_name)

        result = await handler(NukeConnectRequest(client_name="Nuke 16.0v7"))

        assert str(result.result_details) == "Nuke 16.0v7"

    async def test_a_wrong_request_type_raises(self) -> None:
        @verb(NukeConnectRequest)
        async def handler(request: NukeConnectRequest) -> ResultPayload:  # noqa: ARG001
            msg = "must not be reached"
            raise AssertionError(msg)

        with pytest.raises(TypeError, match="Expected NukeConnectRequest, got NukeListWorkflowsRequest"):
            await handler(NukeListWorkflowsRequest())

    async def test_the_class_itself_is_not_an_instance(self) -> None:
        @verb(NukeConnectRequest)
        async def handler(request: NukeConnectRequest) -> ResultPayload:  # noqa: ARG001
            msg = "must not be reached"
            raise AssertionError(msg)

        with pytest.raises(TypeError):
            await handler(NukeConnectRequest)  # type: ignore[arg-type]

    def test_the_handler_keeps_its_identity(self) -> None:
        @verb(NukeConnectRequest)
        async def handle_something(request: RequestPayload) -> ResultPayload:  # noqa: ARG001
            return NukeListWorkflowsResultFailure(result_details="")

        assert handle_something.__name__ == "handle_something"

    def test_a_guarded_handler_stays_a_coroutine_function(self) -> None:
        """A sync verb would run on a side loop with the engine's loop blocked for its duration."""

        @verb(NukeConnectRequest)
        async def handle_something(request: RequestPayload) -> ResultPayload:  # noqa: ARG001
            return NukeListWorkflowsResultFailure(result_details="")

        assert inspect.iscoroutinefunction(handle_something)


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
