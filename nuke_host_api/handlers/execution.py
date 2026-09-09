from __future__ import annotations

from griptape_nodes.retained_mode.events.execution_events import (
    CancelFlowRequest,
    CancelFlowResultSuccess,
    StartFlowRequest,
    StartFlowResultSuccess,
)

from nuke_host_api import engine, parameter_values, shape
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
async def handle_execute_workflow(
    request: NukeExecuteWorkflowRequest,
) -> NukeExecuteWorkflowResultSuccess | NukeExecuteWorkflowResultFailure:
    """Refuse concurrent runs because engine events carry no execution ID.

    The engine's StartFlowRequest resolves when the flow does, so this result reports a run
    that already ended. Progress is the notification stream, not this reply.
    """
    attempted = (
        f"to execute workflow '{request.workflow_id}'" if request.workflow_id else "to execute the loaded workflow"
    )

    if await engine.is_running():
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because=(
                "the engine is already executing. Wait for the current run to "
                "finish, or cancel it with NukeCancelExecutionRequest, then retry."
            ),
            workflow_id=request.workflow_id,
        )

    loaded_id = await engine.current_workflow_id()
    if not loaded_id:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because="no workflow is loaded, so there is nothing to run. Load one with NukeLoadWorkflowRequest.",
            workflow_id=request.workflow_id,
        )

    # A workflow ID is a guard, not an implicit load request.
    if request.workflow_id and request.workflow_id != loaded_id:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because=(
                f"the engine has '{loaded_id}' loaded, not '{request.workflow_id}'. "
                f"Load it with NukeLoadWorkflowRequest first, then execute."
            ),
            workflow_id=request.workflow_id,
        )

    found = await engine.lookup_workflow(loaded_id)
    declared = shape.input_parameter_ids(found.entry) if found.entry is not None else set()

    # Shapeless graphs remain executable when no inputs need validation.
    if request.inputs:
        refusal = parameter_values.unaddressable_inputs_reason(
            loaded_id, found, declared, no_inputs_remedy="send no inputs to run the graph as it stands"
        )
        if refusal is not None:
            return failure(
                NukeExecuteWorkflowResultFailure,
                attempted=attempted,
                because=refusal.because,
                error=refusal.error,
                workflow_id=loaded_id,
            )

    applied, rejected = await parameter_values.apply_inputs(request.inputs, declared)

    flow_name = await engine.top_level_flow_name()
    if flow_name is None:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because="the loaded workflow has no top-level flow to start.",
            workflow_id=loaded_id,
        )

    started = await engine.request(StartFlowRequest(flow_name=flow_name), StartFlowResultSuccess)
    if started.value is None:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because=f"the engine would not run the flow. {started.details}",
            workflow_id=loaded_id,
        )

    return NukeExecuteWorkflowResultSuccess(
        workflow_id=loaded_id,
        state=ExecutionState.COMPLETED,
        applied_inputs=applied,
        rejected_inputs=rejected,
        result_details=f"Ran workflow '{loaded_id}'.",
    )


@verb(NukeGetExecutionStateRequest)
async def handle_get_execution_state(
    request: NukeGetExecutionStateRequest,  # noqa: ARG001
) -> NukeGetExecutionStateResultSuccess | NukeGetExecutionStateResultFailure:
    """Read live flow state so reconnects do not depend on missed notifications."""
    attempted = "to read the engine's execution state"

    flow_name = await engine.top_level_flow_name()
    if flow_name is None:
        return failure(
            NukeGetExecutionStateResultFailure,
            attempted=attempted,
            because="no workflow is loaded, so there is no flow to report on. Load one with NukeLoadWorkflowRequest.",
        )

    state = await engine.flow_state(flow_name)
    if state.value is None:
        return failure(
            NukeGetExecutionStateResultFailure,
            attempted=attempted,
            because=f"the engine could not report it. {state.details}",
        )

    active = list(state.value.resolving_nodes)
    involved = list(state.value.involved_nodes)
    running = engine.flow_is_running(state.value)

    workflow_id = await engine.current_workflow_id()

    return NukeGetExecutionStateResultSuccess(
        running=running,
        active_nodes=active,
        involved_nodes=involved,
        workflow_id=workflow_id,
        result_details=f"Engine is {'running' if running else 'idle'} with {len(involved)} node(s) involved.",
    )


@verb(NukeCancelExecutionRequest)
async def handle_cancel_execution(
    request: NukeCancelExecutionRequest,  # noqa: ARG001
) -> NukeCancelExecutionResultSuccess | NukeCancelExecutionResultFailure:
    """Cancel the only running execution because the engine exposes no execution ID."""
    attempted = "to cancel the running workflow"

    flow_name = await engine.top_level_flow_name()
    if flow_name is None:
        return failure(
            NukeCancelExecutionResultFailure,
            attempted=attempted,
            because="no workflow is loaded, so there is nothing to cancel.",
        )

    cancelled = await engine.request(CancelFlowRequest(flow_name=flow_name), CancelFlowResultSuccess)
    if cancelled.value is None:
        return failure(
            NukeCancelExecutionResultFailure,
            attempted=attempted,
            because=f"the engine refused. {cancelled.details}",
        )

    return NukeCancelExecutionResultSuccess(result_details="Requested cancellation of the running workflow.")
