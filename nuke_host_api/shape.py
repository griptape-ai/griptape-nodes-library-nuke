"""Project engine workflow shapes into host-visible parameters."""

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
    """Accept engine shapes encoded as dictionaries, JSON strings, or missing values."""
    raw_shape = entry.get("workflow_shape")
    if isinstance(raw_shape, dict):
        return raw_shape
    if isinstance(raw_shape, str) and raw_shape.strip():
        try:
            parsed = json.loads(raw_shape)
        except json.JSONDecodeError:
            logger.warning("Could not parse workflow_shape JSON; reporting no parameters.")
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def is_runnable(entry: dict) -> tuple[bool, str]:
    """Reject stale registry entries because ``is_saved`` remains true after file deletion."""
    if not workflow_shape(entry):
        return False, "No declared input/output shape, so a host cannot drive it."

    file_path = entry.get("file_path")
    if not file_path:
        return False, "The registry has no file path for this workflow."

    # Registry paths are workspace-relative.
    absolute_path = Path(WorkflowRegistry.get_complete_file_path(str(file_path)))
    if not absolute_path.exists():
        return False, f"The workflow file is missing from disk: {absolute_path}"

    return True, ""


def data_parameters(section: object) -> Iterator[tuple[str, str, dict]]:
    """Exclude control-flow parameters from the shared publication and allow-list projection."""
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


def declared_parameters(section: object) -> list[dict[str, Any]]:
    """Normalize defaults so declarations and live values share one descriptor shape."""
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


def input_parameter_ids(entry: dict) -> set[tuple[str, str]]:
    """Avoid normalizing defaults because macro normalization issues engine requests."""
    return {
        (node_name, parameter_name)
        for node_name, parameter_name, _ in data_parameters(workflow_shape(entry).get("inputs"))
    }
