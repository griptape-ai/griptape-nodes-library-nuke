"""Bulk parameter-value reads and writes, addressed to whatever the engine has loaded.

Thin, because the reading itself is shared with ``NukeLoadWorkflowRequest``: see
``nuke_host_api.parameter_values`` for how a section is read and why it is read one engine
request at a time. The write half shares its allow-list and its engine calls with
``NukeExecuteWorkflowRequest``, in the same module, so a rejection reads the same way whether
it came from setting a value or from starting a run. What lives here is each verb's own part:
section selection and refusing an unknown section name for the read, and the empty-request and
running-engine refusals for the write.
"""

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
    """Read every declared parameter's current value for one or both sides of the loaded workflow.

    Driven by the same ``workflow_shape`` that ``describe_workflow`` reports, so what a host
    can read back here is exactly what it was told to expect: the same parameters, the same
    normalized descriptor shape as a parameter's ``default`` and as a live
    ``NukeParameterValueEvent``.
    """
    attempted = "to read declared parameter values"

    # Deduplicated before the unknown-name check, not after: a repeated name must not
    # inflate requested_sections or the "N section(s)" count below, since that field's
    # whole job is telling a host what was actually read apart from what came back empty.
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
    """Set values on the loaded workflow's declared inputs, without starting a run.

    Shares its allow-list and its per-pair engine calls with ``NukeExecuteWorkflowRequest``,
    through ``parameter_values.unaddressable_inputs_reason`` and ``parameter_values.apply_inputs``,
    so a rejection reads the same way whether a host got it from setting a value live or from
    starting a run.

    Refuses an empty request outright: unlike execute, where no inputs still means "run the
    graph as it stands," this verb sets values and nothing else, so nothing to set is nothing
    to do. Also refuses while the engine is executing. The engine's own scheduler decides when
    a node's parameter is actually read, so a value set mid-run cannot be told apart from one
    that lands before the node that consumes it or one that lands after, and this layer must
    not answer as if it knows which. A host that wants to stay live with the engine sets
    values between runs; ``NukeCancelExecutionRequest`` is the way out of a run in progress.
    """
    attempted = "to set parameter values on the loaded workflow"

    if not request.inputs:
        return failure(
            NukeSetParameterValuesResultFailure,
            attempted=attempted,
            because="no values were given, so there is nothing to set.",
            error=ValueError,
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
        )

    loaded_id = engine.current_workflow_id()
    if not loaded_id:
        return failure(
            NukeSetParameterValuesResultFailure,
            attempted=attempted,
            because="no workflow is loaded, so there is nothing to set values on. Load one with NukeLoadWorkflowRequest.",
        )

    found = engine.lookup_workflow(loaded_id)
    declared = shape.input_parameter_ids(found.entry) if found.entry is not None else set()

    refusal = parameter_values.unaddressable_inputs_reason(
        loaded_id, found, declared, no_inputs_remedy="send no values, since there is nothing else to do"
    )
    if refusal is not None:
        because, error = refusal
        return failure(
            NukeSetParameterValuesResultFailure,
            attempted=attempted,
            because=because,
            error=error,
            workflow_id=loaded_id,
        )

    applied, rejected = parameter_values.apply_inputs(request.inputs, declared)

    return NukeSetParameterValuesResultSuccess(
        workflow_id=loaded_id,
        applied_inputs=applied,
        rejected_inputs=rejected,
        result_details=f"Set {len(applied)} value(s) on '{loaded_id}', rejected {len(rejected)}.",
    )
