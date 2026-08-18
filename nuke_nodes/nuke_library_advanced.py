from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from griptape_nodes.node_library.advanced_node_library import AdvancedNodeLibrary
from griptape_nodes.node_library.library_registry import Library, LibrarySchema
from griptape_nodes.retained_mode.events.base_events import RequestPayload, ResultPayload
from griptape_nodes.retained_mode.events.workflow_events import (
    PublishWorkflowRegisteredEventData,
    PublishWorkflowRequest,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.events import (
    NukeCancelExecutionRequest,
    NukeConnectRequest,
    NukeDescribeWorkflowRequest,
    NukeExecuteWorkflowRequest,
    NukeGetExecutionStateRequest,
    NukeListWorkflowsRequest,
)
from nuke_host_api.execution_bridge import ExecutionBridge
from nuke_host_api.handlers import _library_version as _host_api_library_version
from nuke_host_api.handlers import (
    handle_cancel_execution,
    handle_connect,
    handle_describe_workflow,
    handle_execute_workflow,
    handle_get_execution_state,
    handle_list_workflows,
)
from nuke_host_api.protocol import PROTOCOL_VERSION
from publish_gizmo.nuke_gizmo_publisher import NukeGizmoPublisher
from publish_gizmo.nuke_publish_options import get_nuke_publish_options

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger("griptape_nodes")

# Subscribes to the engine's execution event feed so host notifications flow outward.
# Module-level so a library reload reuses the same instance and its install/uninstall
# bookkeeping stays coherent.
_HOST_API_BRIDGE = ExecutionBridge()


def _publish_workflow_request_handler(request: RequestPayload) -> ResultPayload:
    if not isinstance(request, PublishWorkflowRequest):
        msg = f"Expected PublishWorkflowRequest, got {type(request).__name__}"
        raise TypeError(msg)

    publisher = NukeGizmoPublisher(
        workflow_name=request.workflow_name,
        metadata=request.metadata,
    )
    return publisher.publish_workflow()


class NukeLibraryAdvanced(AdvancedNodeLibrary):
    """Advanced library implementation for the Nuke Nodes Library."""

    def before_library_nodes_loaded(self, library_data: LibrarySchema, library: Library) -> None:  # noqa: ARG002
        msg = f"Starting to load nodes for '{library_data.name}' library..."
        logger.info(msg)

    def after_library_nodes_loaded(self, library_data: LibrarySchema, library: Library) -> None:  # noqa: ARG002
        GriptapeNodes.LibraryManager().on_register_event_handler(
            request_type=PublishWorkflowRequest,
            handler=_publish_workflow_request_handler,
            library_data=library_data,
            event_data=PublishWorkflowRegisteredEventData(
                start_flow_node_type="NukeStartFlow",
                start_flow_node_library_name=library_data.name,
                end_flow_node_type="NukeEndFlow",
                end_flow_node_library_name=library_data.name,
                get_publish_options=get_nuke_publish_options,
            ),
        )

        # Host API request types are wired by get_request_handlers() below. Outbound events
        # have no equivalent hook, so the bridge subscribes itself here.
        _HOST_API_BRIDGE.install()
        logger.info("Nuke host API ready on protocol version %d", PROTOCOL_VERSION)

    def before_library_unregistered(self, library_data: LibrarySchema, library: Library) -> None:  # noqa: ARG002
        # The engine deregisters request handlers automatically, but execution event
        # listeners are ours to remove. Skipping this leaves the previous bridge subscribed
        # after a reload, and a host then receives every notification twice.
        _HOST_API_BRIDGE.uninstall()
        # _library_version() is cached for the process lifetime, but a library reload without
        # a process restart is a real, handled scenario in this same lifecycle (that is why
        # the bridge above needs an explicit uninstall). An in-place library upgrade must not
        # keep serving the pre-upgrade version to a host that connects after the reload.
        _host_api_library_version.cache_clear()

    def get_request_handlers(
        self,
    ) -> list[
        tuple[
            type[RequestPayload],
            Callable[[RequestPayload], ResultPayload] | Callable[[RequestPayload], Awaitable[ResultPayload]],
        ]
    ]:
        """Return the host API verbs the engine should route to this library.

        Singleton per request type engine-wide, and registered in the orchestrator process
        only. A worker-mode library's handlers are not forwarded, and requests would fail
        with "No manager found".
        """
        return [
            (NukeConnectRequest, handle_connect),
            (NukeListWorkflowsRequest, handle_list_workflows),
            (NukeDescribeWorkflowRequest, handle_describe_workflow),
            (NukeExecuteWorkflowRequest, handle_execute_workflow),
            (NukeGetExecutionStateRequest, handle_get_execution_state),
            (NukeCancelExecutionRequest, handle_cancel_execution),
        ]
