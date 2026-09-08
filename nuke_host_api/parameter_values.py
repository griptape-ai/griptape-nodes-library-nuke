"""Reading a loaded workflow's declared parameter values.

Two verbs answer with these values: ``NukeLoadWorkflowRequest`` returns them once as part of
handing a host everything it needs to build knobs, and ``NukeGetParameterValuesRequest``
returns them on demand afterwards. Sharing the reader is what stops the two from disagreeing
about what a parameter holds, or about how an unreadable one is reported.

Driven by the same ``shape.workflow_shape`` that ``describe_workflow`` publishes, so what a
host can read back is exactly the set of parameters it was told to expect.

One engine request per declared parameter, deliberately, rather than the engine's own
``GetAllNodeInfoRequest``. That request batches a node's metadata, resolution state,
connections, and every parameter's value into one call, which reads like exactly what a bulk
read should use. It does not fit, for three reasons found by reading ``node_manager.py``
rather than the event's docstring:

1. Its ``element_id_to_value`` is keyed by ``parameter.element_id``
   (``NodeManager._set_param_to_value``), not by parameter name. Turning that into the
   ``{node: {parameter: value}}`` shape these verbs promise needs a second lookup, through
   the node's element tree, to recover the name behind each id.
2. Its values are display-serialized: ``_set_param_to_value`` calls ``.to_dict()`` or falls
   back to ``.__dict__`` on anything that is not a Python builtin, so an artifact instance
   arrives as a plain dict rather than the object ``value_types.normalize_value`` inspects
   for a ``.value`` attribute. Handing it a dict silently produces a wrong descriptor rather
   than a wrong answer that shows up in a test.
3. It drops a parameter whose value is ``None`` outright (``if value is not None:``), which
   collides with the rule below that a value the engine truly holds as absent is not the same
   thing as a parameter the engine would not answer for.

``GetParameterValueRequest`` (``parameter_events.py``) has none of those problems: it hands
back the live value alongside ``type``, the exact declared-type hint ``normalize_value`` needs
to disambiguate a bare string, for the one parameter asked about. The cost is one engine
request per declared parameter, and a workflow's declared surface is knobs, not hundreds of
them.

``unaddressable_inputs_reason`` and ``apply_inputs`` are the write side of this module,
shared by ``NukeExecuteWorkflowRequest`` and ``NukeSetParameterValuesRequest``. Both forward a
host's ``{node: {parameter: value}}`` through the same allow-list, built from
``shape.input_parameter_ids``, and the same rejection wording, so a pair either verb turns
away reads identically regardless of which one produced it and a host cannot learn two
different things about what "a declared input" means.
"""

from __future__ import annotations

from typing import Any

from griptape_nodes.retained_mode.events.parameter_events import (
    GetParameterValueRequest,
    GetParameterValueResultSuccess,
    SetParameterValueRequest,
    SetParameterValueResultSuccess,
)

from nuke_host_api import engine, shape
from nuke_host_api.protocol import ParameterSection
from nuke_host_api.value_types import normalize_value


def read_sections(
    declared_shape: dict, sections: list[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Read the requested sides of a loaded workflow's shape.

    Returns start-flow values, end-flow values, and every parameter the engine would not
    answer for, tagged with the section it came from. A section not asked for comes back
    empty rather than absent, so a caller never has to distinguish a missing key from an
    empty one.
    """
    inputs: dict[str, dict[str, Any]] = {}
    outputs: dict[str, dict[str, Any]] = {}
    unavailable: list[dict[str, str]] = []

    if ParameterSection.INPUTS in sections:
        inputs, missing = read_section(declared_shape.get("inputs"))
        unavailable.extend({"section": ParameterSection.INPUTS, **entry} for entry in missing)
    if ParameterSection.OUTPUTS in sections:
        outputs, missing = read_section(declared_shape.get("outputs"))
        unavailable.extend({"section": ParameterSection.OUTPUTS, **entry} for entry in missing)

    return inputs, outputs, unavailable


def read_section(section: object) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Read one shape section, reporting what the engine would not answer for.

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


def unaddressable_inputs_reason(
    loaded_id: str, found: engine.WorkflowLookup, declared: set[tuple[str, str]], *, no_inputs_remedy: str
) -> tuple[str, type[Exception]] | None:
    """Diagnose why declared inputs could not be checked against the loaded workflow.

    Shared by ``NukeExecuteWorkflowRequest`` and ``NukeSetParameterValuesRequest``, the two
    verbs that forward a host's ``{node: {parameter: value}}`` through this allow-list. All
    three causes leave the same empty allow-list behind for unrelated reasons, and each sends
    a host somewhere different: retry the registry, load the workflow again, or fall back to
    ``no_inputs_remedy``. That remedy is the one piece of wording each caller supplies for
    itself, because it is the only place the two verbs actually differ: execute still has a
    graph to run as it stands, and set-values has nothing left to do at all.

    Returns the reason text and the exception type a caller's own ``failure`` call should
    raise with it, or None when nothing is wrong and the caller may forward inputs.
    """
    if not found.registry_readable:
        return (
            f"the engine could not read the workflow registry, so what '{loaded_id}' declares as inputs is "
            f"unknown and the inputs sent could not be checked against it. Retry, or {no_inputs_remedy}.",
            RuntimeError,
        )
    # A stale context key over a live registry: the engine can drop an entry without touching
    # the context stack. Worded as NukeGetParameterValuesRequest words the same engine state,
    # so two verbs do not describe one engine condition two ways.
    if found.entry is None:
        return (
            f"the loaded workflow '{loaded_id}' is no longer in the registry, so the inputs sent could not "
            f"be checked against what it declares. Load it again with NukeLoadWorkflowRequest.",
            KeyError,
        )
    # An unsaved editor graph: the engine keeps it in the registry under an "unsaved:" key with
    # no declared shape. Reachable only with an entry actually found, which is the case this
    # message describes.
    if not declared:
        return (
            f"the loaded workflow '{loaded_id}' declares no input parameters, so none of the inputs sent "
            f"could be applied. An unsaved graph an editor user is working on has no declared shape: save "
            f"it and load it by id, or {no_inputs_remedy}.",
            RuntimeError,
        )
    return None


def apply_inputs(
    inputs: dict[str, dict[str, Any]], allowed: set[tuple[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Set each input on the loaded graph, reporting what stuck and what did not.

    Shared by ``NukeExecuteWorkflowRequest`` and ``NukeSetParameterValuesRequest`` so a
    rejection reads the same way regardless of which verb produced it. A silently dropped
    input is worse than a refusal: the workflow, or the knob a host thinks it just set, carries
    on with the wrong value and produces a plausible-looking result from it. So rejections are
    reported rather than logged and forgotten.

    Only a forwarded pair can be rejected by the engine; everything this function turns away
    itself, a node whose value is not an object of parameters and a pair outside ``allowed``,
    is rejected without a request. So a reason a host did not write is the engine's, and the
    two it did are its own to fix.

    Only pairs the loaded workflow declares as inputs are forwarded. The engine would happily
    set a parameter on any node in the loaded graph, and this transport carries no
    authentication, so a host must not be able to reach past a workflow's published inputs.
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
