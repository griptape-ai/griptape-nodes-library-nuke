"""Bulk value reads: every declared start-flow or end-flow parameter in one call.

``NukeGetParameterValuesRequest`` is one host verb answered by one engine request per declared
parameter, looped rather than batched through the engine's own ``GetAllNodeInfoRequest``. That
choice was not obvious, so it is recorded here rather than left for a later reader to
re-derive from behaviour.

``GetAllNodeInfoRequest`` (``retained_mode/events/node_events.py``) batches a node's
metadata, resolution state, connections, and every parameter's value into one engine
request, which reads like exactly what a bulk read should use. It does not fit this job,
for three reasons found by reading ``node_manager.py`` rather than the event's docstring:

1. Its ``element_id_to_value`` is keyed by ``parameter.element_id``
   (``NodeManager._set_param_to_value``), not by parameter name. Turning that into the
   ``{node: {parameter: value}}`` shape this verb promises needs a second lookup, through
   the node's element tree, to recover the name behind each id.
2. Its values are display-serialized: ``_set_param_to_value`` calls ``.to_dict()`` or falls
   back to ``.__dict__`` on anything that is not a Python builtin, so an artifact instance
   arrives as a plain dict rather than the object ``value_types.normalize_value`` inspects
   for a ``.value`` attribute. Handing it a dict silently produces a wrong descriptor rather
   than a wrong answer that shows up in a test.
3. It drops a parameter whose value is ``None`` outright (``if value is not None:``), which
   collides with this verb's own rule that a value the engine truly holds as absent is not
   the same thing as a parameter the engine would not answer for, tracked instead in
   ``unavailable``.

``GetParameterValueRequest`` (``parameter_events.py``) has none of those problems: it hands
back the live value alongside ``type``, the exact declared-type hint ``normalize_value``
needs to disambiguate a bare string, for the one parameter asked about. The cost is one engine
request per declared parameter, and a workflow's declared surface is knobs, not hundreds of
them.
"""

from __future__ import annotations

from typing import Any

from griptape_nodes.retained_mode.events.parameter_events import (
    GetParameterValueRequest,
    GetParameterValueResultSuccess,
)

from nuke_host_api import engine, shape
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.events import (
    NukeGetParameterValuesRequest,
    NukeGetParameterValuesResultFailure,
    NukeGetParameterValuesResultSuccess,
)
from nuke_host_api.protocol import PARAMETER_SECTIONS, ParameterSection
from nuke_host_api.value_types import normalize_value


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
            because="no workflow is loaded, so there are no parameters to read.",
        )

    entry = engine.workflow_entry(workflow_id)
    if entry is None:
        return failure(
            NukeGetParameterValuesResultFailure,
            attempted=attempted,
            because=f"the loaded workflow '{workflow_id}' is no longer in the registry.",
        )

    declared_shape = shape.workflow_shape(entry)
    inputs: dict[str, dict[str, Any]] = {}
    outputs: dict[str, dict[str, Any]] = {}
    unavailable: list[dict[str, str]] = []

    if ParameterSection.INPUTS in sections:
        inputs, missing = _read_section_values(declared_shape.get("inputs"))
        unavailable.extend({"section": ParameterSection.INPUTS, **entry} for entry in missing)
    if ParameterSection.OUTPUTS in sections:
        outputs, missing = _read_section_values(declared_shape.get("outputs"))
        unavailable.extend({"section": ParameterSection.OUTPUTS, **entry} for entry in missing)

    return NukeGetParameterValuesResultSuccess(
        workflow_id=workflow_id,
        requested_sections=sections,
        inputs=inputs,
        outputs=outputs,
        unavailable=unavailable,
        result_details=f"Read {len(sections)} section(s) of parameter values for '{workflow_id}'.",
    )


def _read_section_values(section: object) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Read one shape section's declared parameters, reporting what the engine would not answer for.

    Omitting an unreadable parameter would read to a host as an empty knob rather than one it
    could not fetch, so every miss is reported in the second return value instead.
    """
    values: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, str]] = []

    for declared in shape.declared_parameters(section):
        attempt = engine.request(
            GetParameterValueRequest(node_name=declared["node"], parameter_name=declared["parameter"]),
            GetParameterValueResultSuccess,
        )
        if attempt.value is None:
            missing.append({"node": declared["node"], "parameter": declared["parameter"], "reason": attempt.details})
            continue
        values.setdefault(declared["node"], {})[declared["parameter"]] = normalize_value(
            attempt.value.value, attempt.value.type
        )

    return values, missing
