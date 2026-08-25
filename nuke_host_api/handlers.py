"""Translation: host verbs in, engine requests out.

The only module that knows both vocabularies. Above it, a host sees the six verbs
and the closed value type set. Below it is the engine's current retained-mode API,
free to churn.
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from griptape_nodes.node_library.workflow_registry import WorkflowRegistry
from griptape_nodes.retained_mode.events.app_events import (
    GetEngineVersionRequest,
    GetEngineVersionResultSuccess,
)
from griptape_nodes.retained_mode.events.base_events import RequestPayload, ResultPayload
from griptape_nodes.retained_mode.events.context_events import (
    GetWorkflowContextRequest,
    GetWorkflowContextSuccess,
)
from griptape_nodes.retained_mode.events.execution_events import (
    CancelFlowRequest,
    CancelFlowResultSuccess,
    GetFlowStateRequest,
    GetFlowStateResultSuccess,
    StartFlowRequest,
    StartFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.flow_events import (
    GetTopLevelFlowRequest,
    GetTopLevelFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.parameter_events import (
    GetParameterValueRequest,
    GetParameterValueResultSuccess,
    SetParameterValueRequest,
    SetParameterValueResultSuccess,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    ListAllWorkflowsRequest,
    ListAllWorkflowsResultSuccess,
    RunWorkflowFromRegistryRequest,
    RunWorkflowFromRegistryResultSuccess,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.events import (
    NukeCancelExecutionRequest,
    NukeCancelExecutionResultFailure,
    NukeCancelExecutionResultSuccess,
    NukeConnectRequest,
    NukeConnectResultFailure,
    NukeConnectResultSuccess,
    NukeDescribeWorkflowRequest,
    NukeDescribeWorkflowResultFailure,
    NukeDescribeWorkflowResultSuccess,
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultFailure,
    NukeExecuteWorkflowResultSuccess,
    NukeGetExecutionStateRequest,
    NukeGetExecutionStateResultFailure,
    NukeGetExecutionStateResultSuccess,
    NukeListWorkflowsRequest,
    NukeListWorkflowsResultFailure,
    NukeListWorkflowsResultSuccess,
)
from nuke_host_api.protocol import (
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    VALUE_TYPES,
    ExecutionState,
)
from nuke_host_api.value_types import CONTROL_PARAM_TYPE, normalize_value, value_type_for_engine_type

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("griptape_nodes")

# Resolved relative to this file, not the process working directory, since a host may
# launch the engine from anywhere.
_LIBRARY_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "griptape-nodes-library.json"


@functools.lru_cache(maxsize=1)
def _library_version() -> str:
    """Return the version this library actually ships, read from its own manifest.

    protocol.py previously carried a hardcoded LIBRARY_VERSION, a third copy of this value
    alongside pyproject.toml's, and the two had already drifted (0.1.0 vs the manifest's
    0.3.0). The manifest is what the engine registers and what a user actually installs, so
    it is the one authoritative source. Read once and cached, since the manifest does not
    change while the process is running.
    """
    try:
        manifest = json.loads(_LIBRARY_MANIFEST_PATH.read_text())
        return str(manifest["metadata"]["library_version"])
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("Could not read library_version from %s", _LIBRARY_MANIFEST_PATH)
        return "unknown"


def event_topic() -> str:
    """Return the topic host notifications are published on.

    Mirrors the app layer's default response topic. A host cannot derive this, so
    NukeConnectRequest hands it over.
    """
    session_id = GriptapeNodes.get_session_id()
    if session_id:
        return f"sessions/{session_id}/response"
    engine_id = GriptapeNodes.get_engine_id()
    if engine_id:
        return f"engines/{engine_id}/response"
    return "response"


def _top_level_flow_name() -> str | None:
    """Return the loaded top-level flow's name, or None when nothing is loaded.

    GetFlowStateRequest and CancelFlowRequest both reject a null flow_name rather than
    defaulting to the current context, so every caller has to resolve it first.
    """
    result = GriptapeNodes.handle_request(GetTopLevelFlowRequest())
    if not isinstance(result, GetTopLevelFlowResultSuccess):
        return None
    return result.flow_name


def _engine_version() -> str:
    result = GriptapeNodes.handle_request(GetEngineVersionRequest())
    if not isinstance(result, GetEngineVersionResultSuccess):
        return "unknown"
    return f"{result.major}.{result.minor}.{result.patch}"


def _workflow_table() -> dict | None:
    """Return the engine's raw workflow dict, or None if the engine refused."""
    result = GriptapeNodes.handle_request(ListAllWorkflowsRequest())
    if not isinstance(result, ListAllWorkflowsResultSuccess):
        return None
    return result.workflows


def _workflow_shape(entry: dict) -> dict:
    """Return workflow_shape as a dict.

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


def _is_runnable(entry: dict) -> tuple[bool, str]:
    """Decide whether a host could actually execute this workflow, and say why not.

    A declared input/output shape is necessary but not sufficient: the registry keeps
    entries whose backing file has been moved or deleted, and its ``is_saved`` flag stays
    True in that case, so it cannot be trusted. A host builds a menu from this answer, and
    an entry that always fails to load is worse than an absent one.
    """
    if not _workflow_shape(entry):
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


def _data_parameters(shape_section: object) -> Iterator[tuple[str, str, dict]]:
    """Yield (node, parameter, parameter dict) for every data parameter in a shape section.

    Control-flow parameters are execution wiring rather than data, so they never reach a
    host. Shared by the describe path and the input allow-list so the two cannot disagree
    about which ports exist.
    """
    if not isinstance(shape_section, dict):
        return
    for node_name, parameters in shape_section.items():
        if not isinstance(parameters, dict):
            continue
        for parameter_name, parameter in parameters.items():
            if not isinstance(parameter, dict):
                continue
            if parameter.get("type") == CONTROL_PARAM_TYPE:
                continue
            yield str(node_name), str(parameter_name), parameter


def _ports(shape_section: object) -> list[dict[str, Any]]:
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
        for node_name, parameter_name, parameter in _data_parameters(shape_section)
    ]


def _declared_input_ports(workflow_id: str) -> set[tuple[str, str]]:
    """Return the (node, parameter) pairs a host may set on this workflow.

    Reads identity only. Building full port descriptors here would normalize every default,
    and normalizing a macro-templated one issues an engine request whose result this caller
    then discards.
    """
    table = _workflow_table()
    entry = table.get(workflow_id) if table else None
    if not isinstance(entry, dict):
        return set()
    return {
        (node_name, parameter_name)
        for node_name, parameter_name, _ in _data_parameters(_workflow_shape(entry).get("inputs"))
    }


def _flow_is_running(state: GetFlowStateResultSuccess) -> bool:
    """Report whether a flow state describes an execution in progress.

    One predicate, used by both the execute guard and the state report, so the two cannot
    disagree about what running means.
    """
    return bool(state.resolving_nodes or state.control_nodes)


def _engine_is_running() -> bool:
    """Report whether the engine is mid-execution."""
    flow_name = _top_level_flow_name()
    if flow_name is None:
        return False
    result = GriptapeNodes.handle_request(GetFlowStateRequest(flow_name=flow_name))
    if not isinstance(result, GetFlowStateResultSuccess):
        return False
    return _flow_is_running(result)


def handle_connect(request: RequestPayload) -> ResultPayload:
    """Agree a protocol version and hand over the event topic."""
    if not isinstance(request, NukeConnectRequest):
        msg = f"Expected NukeConnectRequest, got {type(request).__name__}"
        raise TypeError(msg)

    offered = request.client_protocol_versions or [PROTOCOL_VERSION]
    mutual = sorted(set(offered) & set(SUPPORTED_PROTOCOL_VERSIONS), reverse=True)

    if not mutual:
        details = (
            f"Attempted to connect a host speaking protocol version(s) {offered}. "
            f"Failed because this library supports {list(SUPPORTED_PROTOCOL_VERSIONS)}. "
            f"Update the host plugin, or install a library version that still supports it."
        )
        return NukeConnectResultFailure(
            supported_protocol_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
            exception=ValueError(details),
            result_details=details,
        )

    client = request.client_name or "unnamed host"
    return NukeConnectResultSuccess(
        protocol_version=mutual[0],
        supported_protocol_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
        engine_version=_engine_version(),
        library_version=_library_version(),
        event_topic=event_topic(),
        value_types=list(VALUE_TYPES),
        result_details=f"Connected {client} on host API protocol version {mutual[0]}.",
    )


def handle_list_workflows(request: RequestPayload) -> ResultPayload:
    """Translate to ListAllWorkflowsRequest and narrow the result."""
    if not isinstance(request, NukeListWorkflowsRequest):
        msg = f"Expected NukeListWorkflowsRequest, got {type(request).__name__}"
        raise TypeError(msg)

    table = _workflow_table()
    if table is None:
        details = (
            "Attempted to list workflows for a host. Failed because the engine could not read the workflow registry."
        )
        return NukeListWorkflowsResultFailure(exception=RuntimeError(details), result_details=details)

    workflows = []
    for workflow_id, entry in table.items():
        if not isinstance(entry, dict):
            continue
        runnable, reason = _is_runnable(entry)
        if request.runnable_only and not runnable:
            continue
        workflows.append(
            {
                "id": workflow_id,
                "name": str(entry.get("name") or workflow_id),
                "description": str(entry.get("description") or ""),
                "runnable": runnable,
                "unavailable_reason": reason,
            }
        )

    return NukeListWorkflowsResultSuccess(
        workflows=workflows,
        result_details=f"Listed {len(workflows)} workflow(s) for a host client.",
    )


def handle_describe_workflow(request: RequestPayload) -> ResultPayload:
    """Describe one workflow, narrowing every port type on the way out."""
    if not isinstance(request, NukeDescribeWorkflowRequest):
        msg = f"Expected NukeDescribeWorkflowRequest, got {type(request).__name__}"
        raise TypeError(msg)

    table = _workflow_table()
    if table is None:
        details = (
            f"Attempted to describe workflow '{request.workflow_id}'. "
            f"Failed because the engine could not read the workflow registry."
        )
        return NukeDescribeWorkflowResultFailure(
            workflow_id=request.workflow_id, exception=RuntimeError(details), result_details=details
        )

    entry = table.get(request.workflow_id)
    if not isinstance(entry, dict):
        details = (
            f"Attempted to describe workflow '{request.workflow_id}'. "
            f"Failed because no workflow with that name is registered."
        )
        return NukeDescribeWorkflowResultFailure(
            workflow_id=request.workflow_id, exception=KeyError(details), result_details=details
        )

    shape = _workflow_shape(entry)
    return NukeDescribeWorkflowResultSuccess(
        workflow_id=request.workflow_id,
        name=str(entry.get("name") or request.workflow_id),
        description=str(entry.get("description") or ""),
        inputs=_ports(shape.get("inputs")),
        outputs=_ports(shape.get("outputs")),
        result_details=f"Described workflow '{request.workflow_id}' for a host client.",
    )


def handle_execute_workflow(request: RequestPayload) -> ResultPayload:
    """Load the workflow, apply inputs, then start the flow.

    Three engine requests behind one host verb. The engine has no execute-with-inputs entry
    point: RunWorkflowFromRegistryRequest loads the graph, parameter values are set on
    the loaded start node, and StartFlowRequest executes. A host should not have to know
    that sequence, or that it may change.

    Refuses to start over a run already in progress. Loading a second graph would discard
    the first mid-flight, and with no execution id in the engine's events a host could not
    tell which run the notifications that followed belonged to, nor which one a cancel
    would stop. Serial execution is what makes those two gaps survivable.
    """
    if not isinstance(request, NukeExecuteWorkflowRequest):
        msg = f"Expected NukeExecuteWorkflowRequest, got {type(request).__name__}"
        raise TypeError(msg)

    if _engine_is_running():
        details = (
            f"Attempted to execute workflow '{request.workflow_id}'. "
            f"Failed because the engine is already executing. Wait for the current run to "
            f"finish, or cancel it with NukeCancelExecutionRequest, then retry."
        )
        return NukeExecuteWorkflowResultFailure(
            workflow_id=request.workflow_id, exception=RuntimeError(details), result_details=details
        )

    allowed_inputs = _declared_input_ports(request.workflow_id)

    load_result = GriptapeNodes.handle_request(
        RunWorkflowFromRegistryRequest(workflow_name=request.workflow_id, run_with_clean_slate=True)
    )

    if not isinstance(load_result, RunWorkflowFromRegistryResultSuccess):
        details = (
            f"Attempted to execute workflow '{request.workflow_id}'. "
            f"Failed because the engine could not load it. {load_result.result_details}"
        )
        return NukeExecuteWorkflowResultFailure(
            workflow_id=request.workflow_id, exception=RuntimeError(details), result_details=details
        )

    applied, rejected = _apply_inputs(request.inputs, allowed_inputs)

    flow_name = _top_level_flow_name()
    if flow_name is None:
        details = (
            f"Attempted to execute workflow '{request.workflow_id}'. "
            f"Failed because the loaded workflow has no top-level flow to start."
        )
        return NukeExecuteWorkflowResultFailure(
            workflow_id=request.workflow_id, exception=RuntimeError(details), result_details=details
        )

    start_result = GriptapeNodes.handle_request(StartFlowRequest(flow_name=flow_name))
    if not isinstance(start_result, StartFlowResultSuccess):
        details = (
            f"Attempted to execute workflow '{request.workflow_id}'. "
            f"Failed because the engine would not start the flow. {start_result.result_details}"
        )
        return NukeExecuteWorkflowResultFailure(
            workflow_id=request.workflow_id, exception=RuntimeError(details), result_details=details
        )

    return NukeExecuteWorkflowResultSuccess(
        workflow_id=request.workflow_id,
        state=ExecutionState.RUNNING,
        applied_inputs=applied,
        rejected_inputs=rejected,
        result_details=f"Started workflow '{request.workflow_id}'.",
    )


def _apply_inputs(
    inputs: dict[str, dict[str, Any]], allowed: set[tuple[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Set each input on the loaded graph, reporting what stuck and what did not.

    A silently dropped input is worse than a failed execution: the workflow produces plausible
    output from the wrong values. So rejections are reported rather than logged and
    forgotten.

    Only pairs describe_workflow declared are forwarded. The engine would happily set a
    parameter on any node in the loaded graph, and this transport carries no authentication,
    so a host must not be able to reach past a workflow's published inputs.
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
                        "reason": "Not a declared input port of this workflow.",
                    }
                )
                continue
            result = GriptapeNodes.handle_request(
                SetParameterValueRequest(parameter_name=parameter_name, node_name=node_name, value=value)
            )
            if isinstance(result, SetParameterValueResultSuccess):
                applied.append({"node": node_name, "parameter": parameter_name})
            else:
                rejected.append({"node": node_name, "parameter": parameter_name, "reason": str(result.result_details)})

    return applied, rejected


def handle_get_execution_state(request: RequestPayload) -> ResultPayload:
    """Translate the engine's flow state and read its current output values.

    Holds no state of its own. Outputs come from the engine's live parameter values, so
    this cannot drift from the engine's own view the way a cached copy would, and it
    still works after a host reconnects and has missed every notification.
    """
    if not isinstance(request, NukeGetExecutionStateRequest):
        msg = f"Expected NukeGetExecutionStateRequest, got {type(request).__name__}"
        raise TypeError(msg)

    flow_name = _top_level_flow_name()
    if flow_name is None:
        details = (
            "Attempted to read the engine's execution state. "
            "Failed because no workflow is loaded, so there is no flow to report on."
        )
        return NukeGetExecutionStateResultFailure(exception=RuntimeError(details), result_details=details)

    result = GriptapeNodes.handle_request(GetFlowStateRequest(flow_name=flow_name))
    if not isinstance(result, GetFlowStateResultSuccess):
        details = (
            "Attempted to read the engine's execution state. "
            f"Failed because the engine could not report it. {result.result_details}"
        )
        return NukeGetExecutionStateResultFailure(exception=RuntimeError(details), result_details=details)

    active = list(result.resolving_nodes)
    involved = list(result.involved_nodes)
    running = _flow_is_running(result)

    workflow_id = _current_workflow_id()
    outputs: dict[str, dict[str, Any]] = {}
    if request.include_outputs and workflow_id:
        outputs = _read_output_values(workflow_id)

    return NukeGetExecutionStateResultSuccess(
        running=running,
        active_nodes=active,
        involved_nodes=involved,
        workflow_id=workflow_id,
        outputs=outputs,
        result_details=f"Engine is {'running' if running else 'idle'} with {len(involved)} node(s) involved.",
    )


def _current_workflow_id() -> str:
    """Return the loaded workflow's id, or empty when none is loaded."""
    result = GriptapeNodes.handle_request(GetWorkflowContextRequest())
    if not isinstance(result, GetWorkflowContextSuccess) or not result.workflow_name:
        return ""
    return result.workflow_name


def _read_output_values(workflow_id: str) -> dict[str, dict[str, Any]]:
    """Read the declared output ports' current values, normalized.

    Driven by the same workflow_shape that describe_workflow reports, so what a host can
    read back is exactly what it was told to expect. Ports the engine cannot answer for
    are omitted rather than reported as null, so "absent" and "empty" stay distinct.
    """
    table = _workflow_table()
    entry = table.get(workflow_id) if table else None
    if not isinstance(entry, dict):
        return {}

    outputs: dict[str, dict[str, Any]] = {}
    for port in _ports(_workflow_shape(entry).get("outputs")):
        result = GriptapeNodes.handle_request(
            GetParameterValueRequest(node_name=port["node"], parameter_name=port["parameter"])
        )
        if not isinstance(result, GetParameterValueResultSuccess):
            continue
        outputs.setdefault(port["node"], {})[port["parameter"]] = normalize_value(result.value, result.type)
    return outputs


def handle_cancel_execution(request: RequestPayload) -> ResultPayload:
    """Ask the engine to stop executing.

    Cancels whatever the engine is running, because the engine offers no way to name a
    specific execution. Correct while executions are serial, wrong the moment they are
    not, which is a reason to want an engine-side execution id.
    """
    if not isinstance(request, NukeCancelExecutionRequest):
        msg = f"Expected NukeCancelExecutionRequest, got {type(request).__name__}"
        raise TypeError(msg)

    flow_name = _top_level_flow_name()
    if flow_name is None:
        details = (
            "Attempted to cancel the running workflow. "
            "Failed because no workflow is loaded, so there is nothing to cancel."
        )
        return NukeCancelExecutionResultFailure(exception=RuntimeError(details), result_details=details)

    result = GriptapeNodes.handle_request(CancelFlowRequest(flow_name=flow_name))
    if not isinstance(result, CancelFlowResultSuccess):
        details = (
            f"Attempted to cancel the running workflow. Failed because the engine refused. {result.result_details}"
        )
        return NukeCancelExecutionResultFailure(exception=RuntimeError(details), result_details=details)

    # The terminal state arrives as a NukeExecutionStateEvent when the engine unwinds.
    return NukeCancelExecutionResultSuccess(result_details="Requested cancellation of the running workflow.")
