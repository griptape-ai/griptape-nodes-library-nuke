"""Translation: host verbs in, engine requests out.

One module per verb group, and ``ROUTES`` below is the only place a verb is bound to the
code that answers it. The engine's handler table is keyed by request type, so a verb that
is declared in ``protocol.py`` and never routed here answers nothing at all with no import
error to show for it. Keeping the table beside the handlers rather than in the library
lifecycle module is what lets a test assert the two lists agree.
"""

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
    NukeListProjectsRequest,
    NukeListWorkflowsRequest,
    NukeSetCurrentProjectRequest,
)
from nuke_host_api.handlers.connect import handle_connect
from nuke_host_api.handlers.execution import (
    handle_cancel_execution,
    handle_execute_workflow,
    handle_get_execution_state,
)
from nuke_host_api.handlers.projects import (
    handle_describe_project,
    handle_get_current_project,
    handle_list_projects,
    handle_set_current_project,
)
from nuke_host_api.handlers.workflows import handle_describe_workflow, handle_list_workflows

if TYPE_CHECKING:
    from collections.abc import Callable

    from griptape_nodes.retained_mode.events.base_events import RequestPayload, ResultPayload

ROUTES: tuple[tuple[type[RequestPayload], Callable[[RequestPayload], ResultPayload]], ...] = (
    (NukeConnectRequest, handle_connect),
    (NukeListWorkflowsRequest, handle_list_workflows),
    (NukeDescribeWorkflowRequest, handle_describe_workflow),
    (NukeExecuteWorkflowRequest, handle_execute_workflow),
    (NukeGetExecutionStateRequest, handle_get_execution_state),
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
    "handle_list_projects",
    "handle_list_workflows",
    "handle_set_current_project",
]
