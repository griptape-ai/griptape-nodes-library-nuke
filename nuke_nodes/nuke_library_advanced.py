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

from nuke_host_api import library_version
from nuke_host_api.execution_bridge import uninstall as uninstall_host_api_bridge
from nuke_host_api.handlers import ROUTES
from nuke_host_api.protocol import PROTOCOL_VERSION
from publish_gizmo.nuke_gizmo_publisher import NukeGizmoPublisher
from publish_gizmo.nuke_publish_options import get_nuke_publish_options

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger("griptape_nodes")

PUBLISH_TARGET_ICON = "logos/nuke.png"


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
                display_name="Publish to Nuke Gizmo",
                description="Package the workflow as a versioned .gizmo installed into a Nuke plugin directory.",
                icon=PUBLISH_TARGET_ICON,
            ),
        )

        # The engine-global event bridge waits for a host connection.
        logger.info("Nuke host API ready on protocol version %d", PROTOCOL_VERSION)

    def before_library_unregistered(self, library_data: LibrarySchema, library: Library) -> None:  # noqa: ARG002
        # The engine does not deregister execution listeners on reload.
        uninstall_host_api_bridge()
        # A reload may replace the manifest without restarting the process.
        library_version.reset()

    def get_request_handlers(
        self,
    ) -> list[
        tuple[
            type[RequestPayload],
            Callable[[RequestPayload], ResultPayload] | Callable[[RequestPayload], Awaitable[ResultPayload]],
        ]
    ]:
        """Register each host verb once in the orchestrator; worker handlers are not forwarded."""
        return list(ROUTES)
