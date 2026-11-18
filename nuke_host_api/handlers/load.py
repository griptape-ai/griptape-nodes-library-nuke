"""Load and describe a workflow."""

from __future__ import annotations

import logging

from griptape_nodes.retained_mode.events.context_events import (
    CloseWorkflowRequest,
    CloseWorkflowResultSuccess,
    OpenWorkflowRequest,
    OpenWorkflowResultSuccess,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    ImportWorkflowRequest,
    ImportWorkflowResultSuccess,
)

from nuke_host_api import engine, flow_run, loaded_workflow, parameter_values, run_outcome, shape
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.events import (
    NukeLoadWorkflowRequest,
    NukeLoadWorkflowResultFailure,
    NukeLoadWorkflowResultSuccess,
)
from nuke_host_api.protocol import PARAMETER_SECTIONS

logger = logging.getLogger("griptape_nodes")


@verb(NukeLoadWorkflowRequest, bind_loaded_workflow=False)
async def handle_load_workflow(
    request: NukeLoadWorkflowRequest,
) -> NukeLoadWorkflowResultSuccess | NukeLoadWorkflowResultFailure:
    """Validate before loading because loading replaces the workflow the host's verbs act on."""
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

    # Held for the whole load so an execute cannot start on the graph being torn down.
    with flow_run.reserve() as reserved:
        if reserved and not await _host_workflow_running():
            return await _load(request)

    return failure(
        NukeLoadWorkflowResultFailure,
        attempted=f"to load '{request.workflow_id or request.file_path}'",
        because=(
            "the engine is already executing or loading a workflow, and loading replaces the one in use. "
            "Wait for it to finish, or cancel a run with NukeCancelExecutionRequest, then retry."
        ),
        workflow_id=request.workflow_id,
    )


async def _host_workflow_running() -> bool:
    return await loaded_workflow.running()


async def _load(request: NukeLoadWorkflowRequest) -> NukeLoadWorkflowResultSuccess | NukeLoadWorkflowResultFailure:
    if request.file_path:
        imported = await engine.request(ImportWorkflowRequest(file_path=request.file_path), ImportWorkflowResultSuccess)
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

    # Checked first, so an unknown name never reaches the engine as an open.
    found = await engine.lookup_workflow(workflow_id)
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

    # Opened first, so a failed open leaves the host's previous workflow loaded. A workflow already
    # open, such as an editor tab, comes back as it is, unsaved edits included.
    opened = await engine.request(OpenWorkflowRequest(workflow_name=workflow_id), OpenWorkflowResultSuccess)
    if opened.value is None:
        return failure(
            NukeLoadWorkflowResultFailure,
            attempted=attempted,
            because=f"the engine could not open it. {opened.details}",
            workflow_id=workflow_id,
        )
    open_id = opened.value.open_workflow.workflow_id
    opened_by_host = not opened.value.already_open

    previous = loaded_workflow.current()
    if previous is not None and previous.open_id == open_id:
        # Loading the host's workflow again keeps it, so whether the host opened it doesn't change.
        opened_by_host = previous.opened_by_host
    elif previous is not None and previous.opened_by_host:
        await _close_previous(previous)

    loaded_workflow.record(open_id, workflow_id, opened_by_host=opened_by_host)
    # A load replaces the graph a previous verdict described.
    run_outcome.clear()

    declared_shape = shape.workflow_shape(entry)
    with loaded_workflow.bound():
        input_values, output_values, unavailable = await parameter_values.read_sections(
            declared_shape, list(PARAMETER_SECTIONS)
        )

    return NukeLoadWorkflowResultSuccess(
        workflow_id=workflow_id,
        name=str(entry.get("name") or workflow_id),
        inputs=shape.declared_parameters(declared_shape.get("inputs")),
        outputs=shape.declared_parameters(declared_shape.get("outputs")),
        input_values=input_values,
        output_values=output_values,
        unavailable=unavailable,
        result_details=f"Loaded workflow '{workflow_id}' for a host client.",
    )


async def _close_previous(previous: loaded_workflow.LoadedWorkflow) -> None:
    """Close the workflow the host opened for its previous load. One it found open stays open."""
    closed = await engine.request(CloseWorkflowRequest(workflow_id=previous.open_id), CloseWorkflowResultSuccess)
    if closed.value is None:
        logger.warning(
            "Nuke host API: loading another workflow left '%s', which Nuke opened before, open: %s",
            previous.name,
            closed.details,
        )
