"""Load and describe a workflow."""

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
    """Validate before loading because the engine clears object state before building the graph."""
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

    # Validate registry state before the destructive load.
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
        # Clean-slate loading clears the previous graph before building the replacement.
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
