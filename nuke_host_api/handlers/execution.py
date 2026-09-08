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
        refusal = _refuse_unaddressable_inputs(attempted, loaded_id, found, declared)
        if refusal is not None:
            return refusal

    applied, rejected = _apply_inputs(request.inputs, declared)

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


def _refuse_unaddressable_inputs(
    attempted: str, loaded_id: str, found: engine.WorkflowLookup, declared: set[tuple[str, str]]
) -> NukeExecuteWorkflowResultFailure | None:
    """Refuse inputs nothing could be applied to, naming which of three causes it was.

    All three leave an empty allow-list, and each sends a host somewhere different: retry the
    registry, load the workflow again, or save the graph first. Collapsing any two of them names
    a cause the host cannot act on, and starting the run instead would report success while
    running the author's values.
    """
    if not found.registry_readable:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because=(
                f"the engine could not read the workflow registry, so what '{loaded_id}' declares as inputs is "
                f"unknown and the inputs sent could not be checked against it. Retry, or send no inputs to run "
                f"the graph as it stands."
            ),
            workflow_id=loaded_id,
        )
    # A stale context key over a live registry: the engine can drop an entry without touching
    # the context stack. Worded as NukeGetParameterValuesRequest words the same state, so two
    # verbs do not describe one engine condition two ways.
    if found.entry is None:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because=(
                f"the loaded workflow '{loaded_id}' is no longer in the registry, so the inputs sent could not "
                f"be checked against what it declares. Load it again with NukeLoadWorkflowRequest."
            ),
            error=KeyError,
            workflow_id=loaded_id,
        )
    # An unsaved editor graph: the engine keeps it in the registry under an "unsaved:" key with
    # no declared shape. Reachable only with an entry actually found, which is the case this
    # message describes.
    if not declared:
        return failure(
            NukeExecuteWorkflowResultFailure,
            attempted=attempted,
            because=(
                f"the loaded workflow '{loaded_id}' declares no input parameters, so none of the inputs sent "
                f"could be applied. An unsaved graph an editor user is working on has no declared shape: save "
                f"it and load it by id, or send no inputs to run it as it stands."
            ),
            workflow_id=loaded_id,
        )
    return None


def _apply_inputs(
    inputs: dict[str, dict[str, Any]], allowed: set[tuple[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Set each input on the loaded graph, reporting what stuck and what did not.

    A silently dropped input is worse than a failed execution: the workflow produces plausible
    output from the wrong values. So rejections are reported rather than logged and
    forgotten. Only a forwarded input can be rejected by the engine; everything this function
    turns away itself, a node whose value is not an object of parameters and a pair outside
    ``allowed``, is rejected without a request. So a reason a host did not write is the
    engine's, and the two it did are its own to fix.

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
