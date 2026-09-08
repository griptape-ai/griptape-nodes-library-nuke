"""Loading: put a workflow in the engine and hand back everything needed to drive it.

The only verb that changes which workflow the engine holds. Before it existed, loading was a
side effect of ``NukeExecuteWorkflowRequest``, which left a host unable to see or set a
parameter's live value without starting a run, and left the layer inconsistent about whether a
host knows what is loaded: discovery addressed workflows by id, everything else answered for
whatever execute happened to have loaded last.

One host verb, four engine requests plus one per declared parameter, because the engine has no
load-and-describe entry point: ``ImportWorkflowRequest`` registers a file the engine has not
seen and costs one more, ``RunWorkflowFromRegistryRequest`` builds the graph, and the values
come back one ``GetParameterValueRequest`` at a time. Collapsing them matters more here than
elsewhere: a host doing this itself would have to know that reading a value requires a load,
and that the load it needs clears all object state.

What a refusal costs a host is not uniform, and the failure result says which kind it got.
Every check this handler makes itself is pre-engine and discards nothing. The engine's own load
is not atomic: with ``run_with_clean_slate=True`` it clears all object state before it builds
the graph, so a load that fails inside the workflow file leaves the engine empty.
"""

from __future__ import annotations

from griptape_nodes.retained_mode.events.workflow_events import (
    ImportWorkflowRequest,
    ImportWorkflowResultSuccess,
    RunWorkflowFromRegistryRequest,
    RunWorkflowFromRegistryResultSuccess,
)

from nuke_host_api import engine, parameter_values, shape
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.events import (
    NukeLoadWorkflowRequest,
    NukeLoadWorkflowResultFailure,
    NukeLoadWorkflowResultSuccess,
)
from nuke_host_api.protocol import PARAMETER_SECTIONS


@verb(NukeLoadWorkflowRequest)
def handle_load_workflow(
    request: NukeLoadWorkflowRequest,
) -> NukeLoadWorkflowResultSuccess | NukeLoadWorkflowResultFailure:
    """Load one workflow, then describe and read it in the same reply.

    Every check this handler can make itself is made before the engine is touched, because
    loading clears all object state: a request that fails on its own arguments, or on an id
    that was never registered, must leave whatever was loaded before intact. The engine's own
    load is the exception, and reports ``engine_state_cleared`` when it fails.
    """
    if request.workflow_id and request.file_path:
        return failure(
            NukeLoadWorkflowResultFailure,
            attempted="to load a workflow",
            because=(
                f"both workflow_id '{request.workflow_id}' and file_path '{request.file_path}' were given, "
                f"and they may name different workflows. Send one."
            ),
            error=ValueError,
        )
    if not request.workflow_id and not request.file_path:
        return failure(
            NukeLoadWorkflowResultFailure,
            attempted="to load a workflow",
            because="neither workflow_id nor file_path was given, so there is nothing to load.",
            error=ValueError,
        )

    if engine.is_running():
        return failure(
            NukeLoadWorkflowResultFailure,
            attempted=f"to load '{request.workflow_id or request.file_path}'",
            because=(
                "the engine is already executing, and loading discards the running graph. "
                "Wait for the run to finish, or cancel it with NukeCancelExecutionRequest, then retry."
            ),
            workflow_id=request.workflow_id,
        )

    if request.file_path:
        imported = engine.request(ImportWorkflowRequest(file_path=request.file_path), ImportWorkflowResultSuccess)
        if imported.value is None:
            return failure(
                NukeLoadWorkflowResultFailure,
                attempted=f"to load the workflow file '{request.file_path}'",
                because=f"the engine could not import it. {imported.details}",
            )
        workflow_id = imported.value.workflow_name
    else:
        workflow_id = request.workflow_id

    attempted = f"to load workflow '{workflow_id}'"

    # Read before loading, not after. An unknown id and an unreadable registry are different
    # answers to a host, and neither is worth clearing the engine's state to discover.
    found = engine.lookup_workflow(workflow_id)
    if not found.registry_readable:
        return failure(
            NukeLoadWorkflowResultFailure,
            attempted=attempted,
            because="the engine could not read the workflow registry.",
            workflow_id=workflow_id,
        )
    entry = found.entry
    if entry is None:
        return failure(
            NukeLoadWorkflowResultFailure,
            attempted=attempted,
            because="no workflow with that name is registered.",
            error=KeyError,
            workflow_id=workflow_id,
        )

    loaded = engine.request(
        RunWorkflowFromRegistryRequest(workflow_name=workflow_id, run_with_clean_slate=True),
        RunWorkflowFromRegistryResultSuccess,
    )
    if loaded.value is None:
        # The only refusal that costs a host its previous graph. A clean slate is requested,
        # and the engine clears all object state before it builds the graph, so by the time
        # the workflow file itself fails there is nothing left to keep.
        return failure(
            NukeLoadWorkflowResultFailure,
            attempted=attempted,
            because=(
                f"the engine could not load it, and the engine's object state was cleared before it tried, "
                f"so nothing is loaded now. {loaded.details}"
            ),
            workflow_id=workflow_id,
            engine_state_cleared=True,
        )

    declared_shape = shape.workflow_shape(entry)
    input_values, output_values, unavailable = parameter_values.read_sections(declared_shape, list(PARAMETER_SECTIONS))

    return NukeLoadWorkflowResultSuccess(
        workflow_id=workflow_id,
        name=str(entry.get("name") or workflow_id),
        description=str(entry.get("description") or ""),
        inputs=shape.declared_parameters(declared_shape.get("inputs")),
        outputs=shape.declared_parameters(declared_shape.get("outputs")),
        input_values=input_values,
        output_values=output_values,
        unavailable=unavailable,
        result_details=f"Loaded workflow '{workflow_id}' for a host client.",
    )
