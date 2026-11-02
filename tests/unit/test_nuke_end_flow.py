"""NukeEndFlow stores outputs exactly as the engine hands them; the gizmo runner resolves paths for Nuke."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from griptape.artifacts import ImageUrlArtifact
from griptape_nodes.exe_types.node_types import TrackedParameterOutputValues
from griptape_nodes.retained_mode import engine as engine_module

from nuke_nodes.nuke_end_flow import NukeEndFlow


@pytest.fixture
def node(monkeypatch: pytest.MonkeyPatch) -> NukeEndFlow:
    """A node whose ambient engine is a fake, so building it boots nothing and scaffolds no workspace."""
    monkeypatch.setattr(engine_module, "current_engine", lambda: Mock(name="engine"))
    return NukeEndFlow("Nuke End Flow")


def test_an_artifact_output_keeps_its_macro_so_saved_workflows_carry_no_absolute_path(node: NukeEndFlow) -> None:
    """A Save node hands back {outputs}/... inside an artifact on purpose; the End node must not bake it."""
    artifact = ImageUrlArtifact(value="{outputs}/gen.png")

    node.parameter_output_values["image"] = artifact

    assert node.parameter_output_values["image"] is artifact
    assert node.parameter_output_values["image"].value == "{outputs}/gen.png"


def test_the_output_values_are_the_engines_own_so_its_substitution_rules_apply_unchanged(node: NukeEndFlow) -> None:
    assert type(node.parameter_output_values) is TrackedParameterOutputValues


def test_default_parameters_are_the_status_and_control_set() -> None:
    assert NukeEndFlow.get_default_node_parameter_names() == ["was_successful", "result_details", "exec_in", "failed"]
