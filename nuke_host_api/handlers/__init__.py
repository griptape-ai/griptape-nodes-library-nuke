"""Bind each host verb to its handler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nuke_host_api.events import (
    NukeCancelExecutionRequest,
    NukeConnectRequest,
    NukeDescribeProjectRequest,
    NukeDescribeWorkflowRequest,
    NukeExecuteWorkflowRequest,
    NukeGetCurrentProjectRequest,
    NukeGetExecutionStateRequest,
    NukeGetParameterValuesRequest,
    NukeListProjectsRequest,
    NukeListWorkflowsRequest,
    NukeLoadWorkflowRequest,
    NukeSetCurrentProjectRequest,
    NukeSetParameterValuesRequest,
)
from nuke_host_api.handlers.connect import handle_connect
from nuke_host_api.handlers.execution import (
    handle_cancel_execution,
    handle_execute_workflow,
    handle_get_execution_state,
)
from nuke_host_api.handlers.load import handle_load_workflow
from nuke_host_api.handlers.projects import (
    handle_describe_project,
    handle_get_current_project,
    handle_list_projects,
    handle_set_current_project,
)
from nuke_host_api.handlers.values import handle_get_parameter_values, handle_set_parameter_values
from nuke_host_api.handlers.workflows import handle_describe_workflow, handle_list_workflows

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from griptape_nodes.retained_mode.events.base_events import RequestPayload, ResultPayload

ROUTES: tuple[tuple[type[RequestPayload], Callable[[RequestPayload], Awaitable[ResultPayload]]], ...] = (
    (NukeConnectRequest, handle_connect),
    (NukeListWorkflowsRequest, handle_list_workflows),
    (NukeDescribeWorkflowRequest, handle_describe_workflow),
    (NukeLoadWorkflowRequest, handle_load_workflow),
    (NukeExecuteWorkflowRequest, handle_execute_workflow),
    (NukeGetExecutionStateRequest, handle_get_execution_state),
    (NukeGetParameterValuesRequest, handle_get_parameter_values),
    (NukeSetParameterValuesRequest, handle_set_parameter_values),
    (NukeCancelExecutionRequest, handle_cancel_execution),
    (NukeListProjectsRequest, handle_list_projects),
    (NukeGetCurrentProjectRequest, handle_get_current_project),
    (NukeSetCurrentProjectRequest, handle_set_current_project),
    (NukeDescribeProjectRequest, handle_describe_project),
)

__all__ = [
    "ROUTES",
    "handle_cancel_execution",
    "handle_connect",
    "handle_describe_project",
    "handle_describe_workflow",
    "handle_execute_workflow",
    "handle_get_current_project",
    "handle_get_execution_state",
    "handle_get_parameter_values",
    "handle_list_projects",
    "handle_list_workflows",
    "handle_load_workflow",
    "handle_set_current_project",
    "handle_set_parameter_values",
]
