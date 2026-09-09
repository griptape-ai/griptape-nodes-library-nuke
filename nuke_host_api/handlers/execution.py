"""Execution: start a run, report on it, stop it."""

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
def handle_execute_workflow(
    request: NukeExecuteWorkflowRequest,
) -> NukeExecuteWorkflowResultSuccess | NukeExecuteWorkflowResultFailure:
    """Apply inputs to the loaded workflow, then start the flow.

    Loads nothing. ``NukeLoadWorkflowRequest`` owns that, so this verb cannot discard the
    graph whose parameters a host has just been setting, and a host can set values, read them
    back, and run without the engine rebuilding the graph in between.

    Refuses to start over a run already in progress. With no execution id in the engine's
    events a host could not tell which run the notifications that followed belonged to, nor
    which one a cancel would stop. Serial execution is what makes those two gaps survivable.

    Also refuses inputs it could not apply at all, and says which of three reasons it hit.
    ``current_workflow_id`` answers for any graph the engine holds, including the unsaved one
    an editor user is working on, and an unsaved graph publishes no declared shape to address
    inputs to. An unreadable registry and an entry that has vanished from a readable one leave
    the same empty allow-list behind for unrelated reasons, and each is fixed differently.
    """
    attempted = (
        f"to execute workflow '{request.workflow_id}'" if request.workflow_id else "to execute the loaded workflow"
    )

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

    loaded_id = engine.current_workflow_id()
    if not loaded_id:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because="no workflow is loaded, so there is nothing to run. Load one with NukeLoadWorkflowRequest.",
            workflow_id=request.workflow_id,
        )

    # Refused rather than loaded. Honouring the id would put loading back inside execute, and
    # ignoring it would run a workflow the host did not ask for while reporting success.
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

    found = engine.lookup_workflow(loaded_id)
    declared = shape.input_parameter_ids(found.entry) if found.entry is not None else set()

    # Only checked when there are inputs to check. With none, what the workflow declares does
    # not bear on the run, and a graph with no declared shape is exactly what an empty
    # workflow_id is for.
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

    applied, rejected = parameter_values.apply_inputs(request.inputs, declared)

    flow_name = engine.top_level_flow_name()
    if flow_name is None:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because="the loaded workflow has no top-level flow to start.",
            workflow_id=loaded_id,
        )

    started = engine.request(StartFlowRequest(flow_name=flow_name), StartFlowResultSuccess)
    if started.value is None:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because=f"the engine would not start the flow. {started.details}",
            workflow_id=loaded_id,
        )

    return NukeExecuteWorkflowResultSuccess(
        workflow_id=loaded_id,
        state=ExecutionState.RUNNING,
        applied_inputs=applied,
        rejected_inputs=rejected,
        result_details=f"Started workflow '{loaded_id}'.",
    )


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
            because="no workflow is loaded, so there is no flow to report on. Load one with NukeLoadWorkflowRequest.",
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
