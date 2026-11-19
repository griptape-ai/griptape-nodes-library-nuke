"""Read and write declared parameters on the loaded workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from griptape_nodes.common.sequences.models import MissingItemPolicy
from griptape_nodes.retained_mode.events.os_events import ScanSequencesRequest, ScanSequencesResultSuccess
from griptape_nodes.retained_mode.events.parameter_events import (
    GetParameterValueRequest,
    GetParameterValueResultSuccess,
    SetParameterValueRequest,
    SetParameterValueResultSuccess,
)

from nuke_host_api import engine, shape
from nuke_host_api.protocol import ParameterSection
from nuke_host_api.value_types import (
    UnrepresentableValueError,
    engine_value,
    is_list_type,
    is_sequence_type,
    normalize_value,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping


async def read_sections(
    declared_shape: dict, sections: list[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Unrequested sections remain present but empty."""
    inputs: dict[str, dict[str, Any]] = {}
    outputs: dict[str, dict[str, Any]] = {}
    unavailable: list[dict[str, str]] = []

    if ParameterSection.INPUTS in sections:
        inputs, missing = await read_section(declared_shape.get("inputs"))
        unavailable.extend({"section": ParameterSection.INPUTS, **entry} for entry in missing)
    if ParameterSection.OUTPUTS in sections:
        outputs, missing = await read_section(declared_shape.get("outputs"))
        unavailable.extend({"section": ParameterSection.OUTPUTS, **entry} for entry in missing)

    return inputs, outputs, unavailable


async def read_section(section: object) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Report unreadable parameters separately from empty values."""
    values: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, str]] = []

    for declared in shape.declared_parameters(section):
        attempt = await engine.request(
            GetParameterValueRequest(node_name=declared["node"], parameter_name=declared["parameter"]),
            GetParameterValueResultSuccess,
        )
        if attempt.value is None:
            missing.append({"node": declared["node"], "parameter": declared["parameter"], "reason": attempt.details})
            continue
        try:
            descriptor = normalize_value(attempt.value.value, attempt.value.type)
        except UnrepresentableValueError as e:
            missing.append({"node": declared["node"], "parameter": declared["parameter"], "reason": str(e)})
            continue
        values.setdefault(declared["node"], {})[declared["parameter"]] = descriptor

    return values, missing


def carries_no_values(inputs: Mapping[str, object]) -> bool:
    """A node entry that is not a dict still counts, so malformed entries reach validation."""
    return all(isinstance(parameters, dict) and not parameters for parameters in inputs.values())


class InputRefusal(NamedTuple):
    because: str
    error: type[Exception]


def unaddressable_inputs_reason(
    loaded_id: str,
    declared: Collection[tuple[str, str]],
    *,
    no_inputs_remedy: str | None = None,
) -> InputRefusal | None:
    """Refuse inputs for a workflow that declares none, rather than reject each one as unknown."""
    if declared:
        return None
    alternative_clause = "." if no_inputs_remedy is None else f", or {no_inputs_remedy}."
    return InputRefusal(
        because=(
            f"the loaded workflow '{loaded_id}' declares no input parameters, so none of the inputs sent "
            f"could be applied. A workflow declares its inputs as parameters on a Start Flow node, and needs "
            f"an End Flow node too{alternative_clause}"
        ),
        error=RuntimeError,
    )


async def apply_inputs(
    inputs: dict[str, dict[str, Any]], allowed: Mapping[tuple[str, str], str | None]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Forward only declared inputs, keyed to their engine type, because the engine accepts parameters on any node."""
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
            try:
                value_for_engine = await _engine_input(value, allowed[(node_name, parameter_name)])
            except UnrepresentableValueError as e:
                rejected.append({"node": node_name, "parameter": parameter_name, "reason": str(e)})
                continue
            attempt = await engine.request(
                SetParameterValueRequest(parameter_name=parameter_name, node_name=node_name, value=value_for_engine),
                SetParameterValueResultSuccess,
            )
            if attempt.value is None:
                rejected.append({"node": node_name, "parameter": parameter_name, "reason": attempt.details})
            else:
                applied.append({"node": node_name, "parameter": parameter_name})

    return applied, rejected


async def _engine_input(value: Any, engine_type: str | None) -> Any:
    """Raises UnrepresentableValueError when a sequence input names no frames to rebuild it from."""
    if not is_sequence_type(engine_type):
        return engine_value(value)
    if not is_list_type(engine_type):
        return await _scan_sequence(value)
    if value is None or value == "":
        return []
    items = value if isinstance(value, list) else [value]
    return [await _scan_sequence(item) for item in items]


async def _scan_sequence(value: Any) -> Any:
    """Rebuild the engine's Sequence from the path and range a host read, since a host holds no Sequence."""
    if value is None or value == "":
        return None
    entry = value if isinstance(value, dict) else {"path": value}
    path, first, last = entry.get("path"), entry.get("first"), entry.get("last")
    if not isinstance(path, str) or not path:
        msg = "A sequence input takes a media entry or a path."
        raise UnrepresentableValueError(msg)
    for bound in (first, last):
        if bound is not None and (isinstance(bound, bool) or not isinstance(bound, int)):
            msg = f"A sequence's first and last are whole numbers or null, not {bound!r}."
            raise UnrepresentableValueError(msg)
    # SKIP keeps a gap-ridden range as one Sequence, as a Read with first and last would.
    attempt = await engine.request(
        ScanSequencesRequest(path=path, policy=MissingItemPolicy.SKIP, start_number=first, end_number=last),
        ScanSequencesResultSuccess,
    )
    if attempt.value is None:
        raise UnrepresentableValueError(attempt.details)
    if not attempt.value.has_entries:
        msg = f"No frames found at '{path}'."
        raise UnrepresentableValueError(msg)
    return attempt.value.sequences[0]
