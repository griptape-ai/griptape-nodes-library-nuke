from __future__ import annotations

from unittest import mock

from griptape_nodes.exe_types.node_types import ConfigurationNode, StartNode
from griptape_nodes.retained_mode.events.flow_events import GetTopLevelFlowResultSuccess

from nuke_nodes.nuke_configuration import NukeConfiguration
from publish_gizmo.publish_config import (
    CUSTOM_GIZMO_PATH,
    GIZMO_INSTALL_PATH,
    GIZMO_PATH,
    VERSION,
    saved_publish_config,
)


class _Start(StartNode):
    def process(self) -> None:
        pass


def _flow_with(*nodes: object) -> mock.Mock:
    flow_manager = mock.Mock()
    flow_manager.get_flow_by_name.return_value.nodes = {f"n{i}": node for i, node in enumerate(nodes)}
    return flow_manager


def _saved_with_legacy_start(configuration: dict | None, start_metadata: dict) -> dict:
    start = _Start(name="Start Flow")
    start.metadata.update(start_metadata)
    with mock.patch("publish_gizmo.publish_config.GriptapeNodes") as griptape_nodes:
        griptape_nodes.handle_request.return_value = GetTopLevelFlowResultSuccess(flow_name="canvas", result_details="")
        griptape_nodes.FlowManager.return_value = _flow_with(start)
        return saved_publish_config(configuration)


def test_the_configuration_node_values_are_used_when_the_workflow_has_one() -> None:
    saved = _saved_with_legacy_start({VERSION: 3}, {"publish_config": {VERSION: 7}})

    assert saved == {VERSION: 3}


def test_a_workflow_published_before_the_node_existed_reads_its_start_node_metadata() -> None:
    saved = _saved_with_legacy_start(None, {"publish_config": {VERSION: 7}})

    assert saved == {VERSION: 7}


def test_a_workflow_never_published_has_nothing_saved() -> None:
    saved = _saved_with_legacy_start(None, {})

    assert saved == {}


def test_the_nuke_configuration_node_holds_every_remembered_setting() -> None:
    node = NukeConfiguration(name="Nuke Configuration")

    assert isinstance(node, ConfigurationNode)
    for name in (GIZMO_INSTALL_PATH, CUSTOM_GIZMO_PATH, GIZMO_PATH, VERSION):
        assert node.get_parameter_by_name(name) is not None, name
