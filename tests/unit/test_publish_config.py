from __future__ import annotations

from griptape_nodes.exe_types.node_types import ConfigurationNode

from nuke_nodes.nuke_configuration import NukeConfiguration
from publish_gizmo.publish_config import (
    CUSTOM_GIZMO_PATH,
    GIZMO_INSTALL_PATH,
    GIZMO_PATH,
    VERSION,
    saved_publish_config,
)


def test_the_remembered_configuration_is_returned_as_is() -> None:
    assert saved_publish_config({VERSION: 3}) == {VERSION: 3}


def test_a_workflow_never_published_has_nothing_saved() -> None:
    assert saved_publish_config(None) == {}


def test_the_nuke_configuration_node_holds_every_remembered_setting() -> None:
    node = NukeConfiguration(name="Nuke Configuration")

    assert isinstance(node, ConfigurationNode)
    for name in (GIZMO_INSTALL_PATH, CUSTOM_GIZMO_PATH, GIZMO_PATH, VERSION):
        assert node.get_parameter_by_name(name) is not None, name
