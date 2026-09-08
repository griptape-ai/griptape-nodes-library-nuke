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
"""

from __future__ import annotations

from typing import Any

from griptape_nodes.retained_mode.events.parameter_events import (
    GetParameterValueRequest,
    GetParameterValueResultSuccess,
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
