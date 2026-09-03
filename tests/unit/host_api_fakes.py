"""Engine stand-ins shared by the host API tests.

Every engine request the handlers issue passes through ``nuke_host_api.engine``, so one
patch of that module's ``GriptapeNodes`` symbol is enough to isolate any of them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from griptape_nodes.retained_mode.events.app_events import (
    GetEngineVersionRequest,
    GetEngineVersionResultSuccess,
)
from griptape_nodes.retained_mode.events.execution_events import (
    GetFlowStateRequest,
    GetFlowStateResultSuccess,
    StartFlowRequest,
    StartFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.flow_events import (
    GetTopLevelFlowRequest,
    GetTopLevelFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.parameter_events import (
    SetParameterValueRequest,
    SetParameterValueResultSuccess,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    ListAllWorkflowsRequest,
    ListAllWorkflowsResultSuccess,
    RunWorkflowFromRegistryRequest,
    RunWorkflowFromRegistryResultSuccess,
)

from nuke_host_api import engine

if TYPE_CHECKING:
    import pytest

SHAPE = {
    "inputs": {
        "Start Flow": {
            "exec_out": {"type": "parametercontroltype"},
            "topic": {
                "type": "str",
                "default_value": "a quiet harbour at dusk",
                "tooltip": "What the shot is about.",
                "settable": True,
            },
            "plate": {"type": "ImageUrlArtifact", "default_value": None, "tooltip": "", "settable": False},
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

WORKFLOW_TABLE = {"wf1": {"name": "WF One", "description": "d", "workflow_shape": SHAPE}}

IDLE_FLOW = GetFlowStateResultSuccess(control_nodes=[], resolving_nodes=[], involved_nodes=[], result_details="idle")

ENGINE_VERSION = GetEngineVersionResultSuccess(major=0, minor=97, patch=0, result_details="ok")


class FakeEngine:
    """Dispatches handle_request by request type, recording call order.

    A response may be a real result instance, reused for every call of that type, or a
    callable that receives the request and computes one, needed when the same request
    type is issued more than once with different outcomes (e.g. one SetParameterValueRequest
    per input).
    """

    def __init__(
        self,
        responses: dict[type, Any] | None = None,
        *,
        session_id: str = "session-abc",
        engine_id: str = "engine-xyz",
    ) -> None:
        self._responses = responses or {}
        self._session_id = session_id
        self._engine_id = engine_id
        self.requests: list[Any] = []

    def handle_request(self, request: Any) -> Any:
        self.requests.append(request)
        response = self._responses.get(type(request))
        if response is None:
            msg = f"FakeEngine has no response configured for {type(request).__name__}"
            raise AssertionError(msg)
        return response(request) if callable(response) else response

    def get_session_id(self) -> str:
        return self._session_id

    def get_engine_id(self) -> str:
        return self._engine_id


def use_engine(monkeypatch: pytest.MonkeyPatch, responses: dict[type, Any] | None = None, **kwargs: Any) -> FakeEngine:
    """Install a fake as the one engine the library can reach, and hand it back for assertions."""
    fake = FakeEngine(responses, **kwargs)
    monkeypatch.setattr(engine, "GriptapeNodes", fake)
    return fake


def execute_responses(overrides: dict[type, Any] | None = None) -> dict[type, Any]:
    """Engine responses for a clean execute, so each test overrides only what it is about.

    Execute preflights twice before it loads anything: once to refuse starting over a run in
    progress, once to learn which parameters it may set.
    """
    responses: dict[type, Any] = {
        ListAllWorkflowsRequest: ListAllWorkflowsResultSuccess(workflows=WORKFLOW_TABLE, result_details="ok"),
        GetFlowStateRequest: IDLE_FLOW,
        RunWorkflowFromRegistryRequest: RunWorkflowFromRegistryResultSuccess(result_details="loaded"),
        SetParameterValueRequest: lambda req: SetParameterValueResultSuccess(
            finalized_value=req.value, data_type="str", result_details="set"
        ),
        GetTopLevelFlowRequest: GetTopLevelFlowResultSuccess(flow_name="main", result_details="ok"),
        StartFlowRequest: StartFlowResultSuccess(result_details="started"),
        GetEngineVersionRequest: ENGINE_VERSION,
    }
    responses.update(overrides or {})
    return responses
