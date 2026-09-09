"""Read and write values on the loaded workflow."""

from __future__ import annotations

from nuke_host_api import engine, parameter_values, shape
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.events import (
    NukeGetParameterValuesRequest,
    NukeGetParameterValuesResultFailure,
    NukeGetParameterValuesResultSuccess,
    NukeSetParameterValuesRequest,
    NukeSetParameterValuesResultFailure,
    NukeSetParameterValuesResultSuccess,
)
from nuke_host_api.protocol import PARAMETER_SECTIONS


@verb(NukeGetParameterValuesRequest)
def handle_get_parameter_values(
    request: NukeGetParameterValuesRequest,
) -> NukeGetParameterValuesResultSuccess | NukeGetParameterValuesResultFailure:
    attempted = "to read declared parameter values"

    # Deduplicate before validation so repeated names do not inflate the reported section count.
    sections: list[str] = list(dict.fromkeys(request.sections)) if request.sections else list(PARAMETER_SECTIONS)
    unknown = [section for section in sections if section not in PARAMETER_SECTIONS]
    if unknown:
        return failure(
            NukeGetParameterValuesResultFailure,
            attempted=attempted,
            because=f"section(s) {unknown} are not recognized. Use one or more of {list(PARAMETER_SECTIONS)}.",
            error=ValueError,
        )

    workflow_id = engine.current_workflow_id()
    if not workflow_id:
        return failure(
            NukeGetParameterValuesResultFailure,
            attempted=attempted,
            because="no workflow is loaded, so there are no parameters to read. Load one with NukeLoadWorkflowRequest.",
        )

    entry = engine.workflow_entry(workflow_id)
    if entry is None:
        return failure(
            NukeGetParameterValuesResultFailure,
            attempted=attempted,
            because=f"the loaded workflow '{workflow_id}' is no longer in the registry.",
        )

    inputs, outputs, unavailable = parameter_values.read_sections(shape.workflow_shape(entry), sections)

    return NukeGetParameterValuesResultSuccess(
        workflow_id=workflow_id,
        requested_sections=sections,
        inputs=inputs,
        outputs=outputs,
        unavailable=unavailable,
        result_details=f"Read {len(sections)} section(s) of parameter values for '{workflow_id}'.",
    )


@verb(NukeSetParameterValuesRequest)
def handle_set_parameter_values(
    request: NukeSetParameterValuesRequest,
) -> NukeSetParameterValuesResultSuccess | NukeSetParameterValuesResultFailure:
    """Refuse writes during execution because parameter-read timing is unavailable."""
    attempted = "to set parameter values on the loaded workflow"
    loaded_id = engine.current_workflow_id()

    nothing_to_act_on = all(isinstance(parameters, dict) and not parameters for parameters in request.inputs.values())
    if nothing_to_act_on:
        return failure(
            NukeSetParameterValuesResultFailure,
            attempted=attempted,
            because="no values were given, so there is nothing to set.",
            error=ValueError,
            workflow_id=loaded_id,
        )

    if engine.is_running():
        return failure(
            NukeSetParameterValuesResultFailure,
            attempted=attempted,
            because=(
                "the engine is already executing, and a value set mid-run cannot be told apart from one that "
                "arrives in time for the node that reads it or one that arrives too late. Wait for the current "
                "run to finish, or cancel it with NukeCancelExecutionRequest, then retry."
            ),
            workflow_id=loaded_id,
        )

    if not loaded_id:
        return failure(
            NukeSetParameterValuesResultFailure,
            attempted=attempted,
            because="no workflow is loaded, so there is nothing to set values on. Load one with NukeLoadWorkflowRequest.",
        )

    found = engine.lookup_workflow(loaded_id)
    declared = shape.input_parameter_ids(found.entry) if found.entry is not None else set()

    refusal = parameter_values.unaddressable_inputs_reason(loaded_id, found, declared)
    if refusal is not None:
        return failure(
            NukeSetParameterValuesResultFailure,
            attempted=attempted,
            because=refusal.because,
            error=refusal.error,
            workflow_id=loaded_id,
        )

    applied, rejected = parameter_values.apply_inputs(request.inputs, declared)

    return NukeSetParameterValuesResultSuccess(
        workflow_id=loaded_id,
        applied_inputs=applied,
        rejected_inputs=rejected,
        result_details=f"Set {len(applied)} value(s) on '{loaded_id}', rejected {len(rejected)}.",
    )
