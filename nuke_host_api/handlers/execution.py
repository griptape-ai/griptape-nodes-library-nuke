"""Execution: start a run, report on it, stop it."""

from __future__ import annotations

from typing import Any

from griptape_nodes.retained_mode.events.execution_events import (
    CancelFlowRequest,
    CancelFlowResultSuccess,
    StartFlowRequest,
    StartFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.parameter_events import (
    SetParameterValueRequest,
    SetParameterValueResultSuccess,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    RunWorkflowFromRegistryRequest,
    RunWorkflowFromRegistryResultSuccess,
)

from nuke_host_api import engine, shape
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.events import (
    NukeCancelExecutionRequest,
    NukeCancelExecutionResultFailure,
    NukeCancelExecutionResultSuccess,
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultFailure,
    NukeExecuteWorkflowResultSuccess,
    NukeGetExecutionStateRequest,
    NukeGetExecutionStateResultFailure,
    NukeGetExecutionStateResultSuccess,
)
from nuke_host_api.protocol import ExecutionState


@verb(NukeExecuteWorkflowRequest)
def handle_execute_workflow(
    request: NukeExecuteWorkflowRequest,
) -> NukeExecuteWorkflowResultSuccess | NukeExecuteWorkflowResultFailure:
    """Load the workflow, apply inputs, then start the flow.

    Three engine requests behind one host verb. The engine has no execute-with-inputs entry
    point: RunWorkflowFromRegistryRequest loads the graph, parameter values are set on
    the loaded start node, and StartFlowRequest executes. A host should not have to know
    that sequence, or that it may change.

    Refuses to start over a run already in progress. Loading a second graph would discard
    the first mid-flight, and with no execution id in the engine's events a host could not
    tell which run the notifications that followed belonged to, nor which one a cancel
    would stop. Serial execution is what makes those two gaps survivable.
    """
    attempted = f"to execute workflow '{request.workflow_id}'"

    if engine.is_running():
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because=(
                "the engine is already executing. Wait for the current run to "
                "finish, or cancel it with NukeCancelExecutionRequest, then retry."
            ),
            workflow_id=request.workflow_id,
        )

    allowed_inputs = _declared_input_parameters(request.workflow_id)

    loaded = engine.request(
        RunWorkflowFromRegistryRequest(workflow_name=request.workflow_id, run_with_clean_slate=True),
        RunWorkflowFromRegistryResultSuccess,
    )
    if loaded.value is None:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because=f"the engine could not load it. {loaded.details}",
            workflow_id=request.workflow_id,
        )

    applied, rejected = _apply_inputs(request.inputs, allowed_inputs)

    flow_name = engine.top_level_flow_name()
    if flow_name is None:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because="the loaded workflow has no top-level flow to start.",
            workflow_id=request.workflow_id,
        )

    started = engine.request(StartFlowRequest(flow_name=flow_name), StartFlowResultSuccess)
    if started.value is None:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because=f"the engine would not start the flow. {started.details}",
            workflow_id=request.workflow_id,
        )

    return NukeExecuteWorkflowResultSuccess(
        workflow_id=request.workflow_id,
        state=ExecutionState.RUNNING,
        applied_inputs=applied,
        rejected_inputs=rejected,
        result_details=f"Started workflow '{request.workflow_id}'.",
    )


def _declared_input_parameters(workflow_id: str) -> set[tuple[str, str]]:
    """Return the parameters a host may set, or nothing when the workflow cannot be read."""
    entry = engine.workflow_entry(workflow_id)
    if entry is None:
        return set()
    return shape.input_parameter_ids(entry)


def _apply_inputs(
    inputs: dict[str, dict[str, Any]], allowed: set[tuple[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Set each input on the loaded graph, reporting what stuck and what did not.

    A silently dropped input is worse than a failed execution: the workflow produces plausible
    output from the wrong values. So rejections are reported rather than logged and
    forgotten.

    Only pairs describe_workflow declared are forwarded. The engine would happily set a
    parameter on any node in the loaded graph, and this transport carries no authentication,
    so a host must not be able to reach past a workflow's published inputs.
    """
    applied: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []

    for node_name, parameters in inputs.items():
        if not isinstance(parameters, dict):
            rejected.append({"node": str(node_name), "parameter": "*", "reason": "Expected an object of parameters."})
            continue
        for parameter_name, value in parameters.items():
            if (node_name, parameter_name) not in allowed:
                rejected.append(
                    {
                        "node": node_name,
                        "parameter": parameter_name,
                        "reason": "Not a declared input parameter of this workflow.",
                    }
                )
                continue
            attempt = engine.request(
                SetParameterValueRequest(parameter_name=parameter_name, node_name=node_name, value=value),
                SetParameterValueResultSuccess,
            )
            if attempt.value is None:
                rejected.append({"node": node_name, "parameter": parameter_name, "reason": attempt.details})
            else:
                applied.append({"node": node_name, "parameter": parameter_name})

    return applied, rejected


@verb(NukeGetExecutionStateRequest)
def handle_get_execution_state(
    request: NukeGetExecutionStateRequest,  # noqa: ARG001
) -> NukeGetExecutionStateResultSuccess | NukeGetExecutionStateResultFailure:
    """Translate the engine's flow state.

    Holds no state of its own, so this cannot drift from the engine's own view the way a
    cached copy would, and it still works after a host reconnects and has missed every
    notification. Reports execution state only: a workflow's parameter values are a separate
    read, ``NukeGetParameterValuesRequest``, because each one costs an engine round trip per
    parameter and a host polling only for liveness should not pay for it.
    """
    attempted = "to read the engine's execution state"

    flow_name = engine.top_level_flow_name()
    if flow_name is None:
        return failure(
            NukeGetExecutionStateResultFailure,
            attempted=attempted,
            because="no workflow is loaded, so there is no flow to report on.",
        )

    state = engine.flow_state(flow_name)
    if state.value is None:
        return failure(
            NukeGetExecutionStateResultFailure,
            attempted=attempted,
            because=f"the engine could not report it. {state.details}",
        )

    active = list(state.value.resolving_nodes)
    involved = list(state.value.involved_nodes)
    running = engine.flow_is_running(state.value)

    workflow_id = engine.current_workflow_id()

    return NukeGetExecutionStateResultSuccess(
        running=running,
        active_nodes=active,
        involved_nodes=involved,
        workflow_id=workflow_id,
        result_details=f"Engine is {'running' if running else 'idle'} with {len(involved)} node(s) involved.",
    )


@verb(NukeCancelExecutionRequest)
def handle_cancel_execution(
    request: NukeCancelExecutionRequest,  # noqa: ARG001
) -> NukeCancelExecutionResultSuccess | NukeCancelExecutionResultFailure:
    """Ask the engine to stop executing.

    Cancels whatever the engine is running, because the engine offers no way to name a
    specific execution. Correct while executions are serial, wrong the moment they are
    not, which is a reason to want an engine-side execution id.
    """
    attempted = "to cancel the running workflow"

    flow_name = engine.top_level_flow_name()
    if flow_name is None:
        return failure(
            NukeCancelExecutionResultFailure,
            attempted=attempted,
            because="no workflow is loaded, so there is nothing to cancel.",
        )

    cancelled = engine.request(CancelFlowRequest(flow_name=flow_name), CancelFlowResultSuccess)
    if cancelled.value is None:
        return failure(
            NukeCancelExecutionResultFailure,
            attempted=attempted,
            because=f"the engine refused. {cancelled.details}",
        )

    # The terminal state arrives as a NukeExecutionStateEvent when the engine unwinds.
    return NukeCancelExecutionResultSuccess(result_details="Requested cancellation of the running workflow.")
