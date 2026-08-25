"""Workflow discovery: what a host may run, and what each one's ports are."""

from __future__ import annotations

from nuke_host_api import shape
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.engine import workflow_table
from nuke_host_api.events import (
    NukeDescribeWorkflowRequest,
    NukeDescribeWorkflowResultFailure,
    NukeDescribeWorkflowResultSuccess,
    NukeListWorkflowsRequest,
    NukeListWorkflowsResultFailure,
    NukeListWorkflowsResultSuccess,
)


@verb(NukeListWorkflowsRequest)
def handle_list_workflows(
    request: NukeListWorkflowsRequest,
) -> NukeListWorkflowsResultSuccess | NukeListWorkflowsResultFailure:
    """Translate to ListAllWorkflowsRequest and narrow the result."""
    table = workflow_table()
    if table is None:
        return failure(
            NukeListWorkflowsResultFailure,
            attempted="to list workflows for a host",
            because="the engine could not read the workflow registry.",
        )

    workflows = []
    for workflow_id, entry in table.items():
        if not isinstance(entry, dict):
            continue
        runnable, reason = shape.is_runnable(entry)
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


@verb(NukeDescribeWorkflowRequest)
def handle_describe_workflow(
    request: NukeDescribeWorkflowRequest,
) -> NukeDescribeWorkflowResultSuccess | NukeDescribeWorkflowResultFailure:
    """Describe one workflow, narrowing every port type on the way out.

    Reads the table rather than a single entry, because an unreadable registry and an
    unknown id are different answers to a host: one is worth retrying, the other never is.
    """
    table = workflow_table()
    if table is None:
        return failure(
            NukeDescribeWorkflowResultFailure,
            attempted=f"to describe workflow '{request.workflow_id}'",
            because="the engine could not read the workflow registry.",
            workflow_id=request.workflow_id,
        )

    entry = table.get(request.workflow_id)
    if not isinstance(entry, dict):
        return failure(
            NukeDescribeWorkflowResultFailure,
            attempted=f"to describe workflow '{request.workflow_id}'",
            because="no workflow with that name is registered.",
            error=KeyError,
            workflow_id=request.workflow_id,
        )

    workflow_shape = shape.workflow_shape(entry)
    return NukeDescribeWorkflowResultSuccess(
        workflow_id=request.workflow_id,
        name=str(entry.get("name") or request.workflow_id),
        description=str(entry.get("description") or ""),
        inputs=shape.ports(workflow_shape.get("inputs")),
        outputs=shape.ports(workflow_shape.get("outputs")),
        result_details=f"Described workflow '{request.workflow_id}' for a host client.",
    )
