from __future__ import annotations

import asyncio

from nuke_host_api import shape
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.engine import lookup_workflow, thumbnail_url, workflow_table
from nuke_host_api.events import (
    NukeDescribeWorkflowRequest,
    NukeDescribeWorkflowResultFailure,
    NukeDescribeWorkflowResultSuccess,
    NukeListWorkflowsRequest,
    NukeListWorkflowsResultFailure,
    NukeListWorkflowsResultSuccess,
)


@verb(NukeListWorkflowsRequest)
async def handle_list_workflows(
    request: NukeListWorkflowsRequest,
) -> NukeListWorkflowsResultSuccess | NukeListWorkflowsResultFailure:
    table = await workflow_table()
    if table is None:
        return failure(
            NukeListWorkflowsResultFailure,
            attempted="to list workflows for a host",
            because="the engine could not read the workflow registry.",
        )

    workflows = []
    images = []
    for workflow_id, entry in table.items():
        if not isinstance(entry, dict) or entry.get("is_internal"):
            continue
        runnable, reason = shape.is_runnable(entry)
        if request.runnable_only and not runnable:
            continue
        library_provided = bool(entry.get("is_griptape_provided"))
        # The engine opens a library's workflow as a copy whatever its is_template says.
        template = library_provided or bool(entry.get("is_template"))
        if request.templates_only and not template:
            continue
        workflows.append(
            {
                "id": workflow_id,
                "name": str(entry.get("name") or workflow_id),
                "description": str(entry.get("description") or ""),
                "runnable": runnable,
                "unavailable_reason": reason,
                "template": template,
                "library_provided": library_provided,
            }
        )
        images.append(str(entry.get("image") or ""))

    urls = await asyncio.gather(*(thumbnail_url(image) for image in images))
    for workflow, url in zip(workflows, urls, strict=True):
        workflow["thumbnail_url"] = url

    return NukeListWorkflowsResultSuccess(
        workflows=workflows,
        result_details=f"Listed {len(workflows)} workflow(s) for a host client.",
    )


@verb(NukeDescribeWorkflowRequest)
async def handle_describe_workflow(
    request: NukeDescribeWorkflowRequest,
) -> NukeDescribeWorkflowResultSuccess | NukeDescribeWorkflowResultFailure:
    """Distinguish an unreadable registry from an unknown workflow ID."""
    found = await lookup_workflow(request.workflow_id)
    if not found.registry_readable:
        return failure(
            NukeDescribeWorkflowResultFailure,
            attempted=f"to describe workflow '{request.workflow_id}'",
            because="the engine could not read the workflow registry.",
            workflow_id=request.workflow_id,
        )

    entry = found.entry
    if entry is None:
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
        inputs=shape.declared_parameters(workflow_shape.get("inputs")),
        outputs=shape.declared_parameters(workflow_shape.get("outputs")),
        result_details=f"Described workflow '{request.workflow_id}' for a host client.",
    )
