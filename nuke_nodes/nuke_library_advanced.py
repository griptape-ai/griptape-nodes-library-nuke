import logging

from griptape_nodes.node_library.advanced_node_library import AdvancedNodeLibrary
from griptape_nodes.node_library.library_registry import Library, LibrarySchema
from griptape_nodes.retained_mode.events.base_events import RequestPayload, ResultPayload
from griptape_nodes.retained_mode.events.workflow_events import (
    PublishWorkflowRegisteredEventData,
    PublishWorkflowRequest,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from publish_gizmo.nuke_gizmo_publisher import NukeGizmoPublisher
from publish_gizmo.nuke_publish_options import get_nuke_publish_options

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("griptape_nodes")


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
