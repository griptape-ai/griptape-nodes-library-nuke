"""Projection of the engine's workflow_shape into host-visible ports.

Reads registry entries and shape sections only, so it never issues an engine request of its
own and needs no engine fake to test. Both verbs that publish ports and both that consume
them go through here, so a host cannot be told one thing by describe and another by
execute.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from griptape_nodes.node_library.workflow_registry import WorkflowRegistry

from nuke_host_api.value_types import CONTROL_PARAM_TYPE, normalize_value, value_type_for_engine_type

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("griptape_nodes")


def workflow_shape(entry: dict) -> dict:
    """Return a registry entry's workflow_shape as a dict.

    The engine sends this field as a JSON *string* for some workflows and omits it for
    others. Absorbing that inconsistency is this layer's job; a host must never have to
    know about it.
    """
    raw_shape = entry.get("workflow_shape")
    if isinstance(raw_shape, dict):
        return raw_shape
    if isinstance(raw_shape, str) and raw_shape.strip():
        try:
            parsed = json.loads(raw_shape)
        except json.JSONDecodeError:
            logger.warning("Could not parse workflow_shape JSON; reporting no ports.")
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def is_runnable(entry: dict) -> tuple[bool, str]:
    """Decide whether a host could actually execute this workflow, and say why not.

    A declared input/output shape is necessary but not sufficient: the registry keeps
    entries whose backing file has been moved or deleted, and its ``is_saved`` flag stays
    True in that case, so it cannot be trusted. A host builds a menu from this answer, and
    an entry that always fails to load is worse than an absent one.
    """
    if not workflow_shape(entry):
        return False, "No declared input/output shape, so a host cannot drive it."

    file_path = entry.get("file_path")
    if not file_path:
        return False, "The registry has no file path for this workflow."

    # Registry paths are workspace-relative, so they are resolved through the engine's own
    # resolver rather than against the process working directory.
    absolute_path = Path(WorkflowRegistry.get_complete_file_path(str(file_path)))
    if not absolute_path.exists():
        return False, f"The workflow file is missing from disk: {absolute_path}"

    return True, ""


def data_parameters(section: object) -> Iterator[tuple[str, str, dict]]:
    """Yield (node, parameter, parameter dict) for every data parameter in a shape section.

    Control-flow parameters are execution wiring rather than data, so they never reach a
    host. Shared by the describe path and the input allow-list so the two cannot disagree
    about which ports exist.
    """
    if not isinstance(section, dict):
        return
    for node_name, parameters in section.items():
        if not isinstance(parameters, dict):
            continue
        for parameter_name, parameter in parameters.items():
            if not isinstance(parameter, dict):
                continue
            if parameter.get("type") == CONTROL_PARAM_TYPE:
                continue
            yield str(node_name), str(parameter_name), parameter


def ports(section: object) -> list[dict[str, Any]]:
    """Flatten a workflow_shape section into host-visible ports.

    The engine hands back ``{node: {parameter: {...20+ keys...}}}`` where the inner dict
    changes shape between releases. A host needs enough to build a knob and nothing that
    ties it to engine vocabulary, so the width stops here: identity, host type, the
    author's default, help text, and whether it may be set. Unrecognized types degrade into
    the closed host set.

    ``default`` is a normalized descriptor rather than a raw engine value, so a port's
    default and its live value arrive in the same shape.
    """
    return [
        {
            "node": node_name,
            "parameter": parameter_name,
            "name": f"{node_name}.{parameter_name}",
            "type": value_type_for_engine_type(parameter.get("type")),
            "default": normalize_value(parameter.get("default_value"), parameter.get("type")),
            "tooltip": str(parameter.get("tooltip") or ""),
            "settable": bool(parameter.get("settable", True)),
        }
        for node_name, parameter_name, parameter in data_parameters(section)
    ]


def input_port_ids(entry: dict) -> set[tuple[str, str]]:
    """Return the (node, parameter) pairs a host may set on this workflow.

    Reads identity only. Building full port descriptors here would normalize every default,
    and normalizing a macro-templated one issues an engine request whose result this caller
    then discards.
    """
    return {
        (node_name, parameter_name)
        for node_name, parameter_name, _ in data_parameters(workflow_shape(entry).get("inputs"))
    }
