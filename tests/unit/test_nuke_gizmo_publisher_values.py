"""Tests that values set on the canvas reach the gizmo's knobs.

``extract_workflow_shape`` reports declared defaults only. Every NukeStartFlow input is
user-added with a declared default of None, so without this overlay the gizmo's knobs are
written with no value line and Nuke initializes them to 0 / empty.
"""

from __future__ import annotations

from unittest import mock

from publish_gizmo.nuke_gizmo_publisher import NukeGizmoPublisher


def _overlay(shape: dict, node: mock.Mock) -> dict:
    with mock.patch("publish_gizmo.nuke_gizmo_publisher.GriptapeNodes") as griptape_nodes:
        griptape_nodes.NodeManager.return_value.get_node_by_name.return_value = node
        NukeGizmoPublisher._overlay_current_values(shape)  # noqa: SLF001
    return shape


def _shape(params: dict) -> dict:
    return {"input": {"Nuke Start Flow": params}, "output": {"Nuke End Flow": {}}}


def _node(parameter_values: dict) -> mock.Mock:
    node = mock.Mock()
    node.parameter_values = parameter_values
    node.get_parameter_value.side_effect = parameter_values.get
    return node


class TestOverlayCurrentValues:
    def test_set_value_replaces_the_declared_default(self) -> None:
        shape = _overlay(
            _shape({"seed": {"type": "int", "default_value": None}}),
            _node({"seed": 42}),
        )
        assert shape["input"]["Nuke Start Flow"]["seed"]["default_value"] == 42

    def test_unset_param_keeps_its_declared_default(self) -> None:
        shape = _overlay(
            _shape({"seed": {"type": "int", "default_value": 7}}),
            _node({}),
        )
        assert shape["input"]["Nuke Start Flow"]["seed"]["default_value"] == 7

    def test_falsy_set_value_is_still_applied(self) -> None:
        shape = _overlay(
            _shape({"enabled": {"type": "bool", "default_value": True}}),
            _node({"enabled": False}),
        )
        assert shape["input"]["Nuke Start Flow"]["enabled"]["default_value"] is False

    def test_lookup_failure_leaves_the_declared_default(self) -> None:
        """Value introspection is best-effort; it must never fail a publish."""
        node = _node({"seed": 42})
        node.get_parameter_value.side_effect = RuntimeError("boom")
        shape = _overlay(_shape({"seed": {"type": "int", "default_value": 7}}), node)
        assert shape["input"]["Nuke Start Flow"]["seed"]["default_value"] == 7

    def test_missing_node_leaves_the_shape_untouched(self) -> None:
        shape = _shape({"seed": {"type": "int", "default_value": 7}})
        with mock.patch("publish_gizmo.nuke_gizmo_publisher.GriptapeNodes") as griptape_nodes:
            griptape_nodes.NodeManager.return_value.get_node_by_name.side_effect = KeyError("gone")
            NukeGizmoPublisher._overlay_current_values(shape)  # noqa: SLF001
        assert shape["input"]["Nuke Start Flow"]["seed"]["default_value"] == 7

    def test_shape_without_inputs_is_tolerated(self) -> None:
        shape = {"output": {}}
        _overlay(shape, _node({}))
        assert shape == {"output": {}}
