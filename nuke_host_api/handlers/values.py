"""Bulk value reads: every declared start-flow or end-flow parameter in one call.

Thin, because the reading itself is shared with ``NukeLoadWorkflowRequest``: see
``nuke_host_api.parameter_values`` for how a section is read and why it is read one engine
request at a time. What lives here is the part that is this verb's own, which is section
selection and refusing a name that is not a section.
"""

from __future__ import annotations

from nuke_host_api import engine, parameter_values, shape
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.events import (
    NukeGetParameterValuesRequest,
    NukeGetParameterValuesResultFailure,
    NukeGetParameterValuesResultSuccess,
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
