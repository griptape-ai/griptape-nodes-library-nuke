"""NukeEndFlow stores outputs exactly as the engine hands them; the gizmo runner resolves paths for Nuke."""

from __future__ import annotations

from griptape.artifacts import ImageUrlArtifact
from griptape_nodes.exe_types.node_types import TrackedParameterOutputValues

from nuke_nodes.nuke_end_flow import NukeEndFlow


def test_an_artifact_output_keeps_its_macro_so_saved_workflows_carry_no_absolute_path() -> None:
    """A Save node hands back {outputs}/... inside an artifact on purpose; the End node must not bake it."""
    node = NukeEndFlow("Nuke End Flow")
    artifact = ImageUrlArtifact(value="{outputs}/gen.png")

    node.parameter_output_values["image"] = artifact

    assert node.parameter_output_values["image"] is artifact
    assert node.parameter_output_values["image"].value == "{outputs}/gen.png"


def test_the_output_values_are_the_engines_own_so_its_substitution_rules_apply_unchanged() -> None:
    node = NukeEndFlow("Nuke End Flow")

    assert type(node.parameter_output_values) is TrackedParameterOutputValues


def test_default_parameters_are_the_status_and_control_set() -> None:
    assert NukeEndFlow.get_default_node_parameter_names() == ["was_successful", "result_details", "exec_in", "failed"]
