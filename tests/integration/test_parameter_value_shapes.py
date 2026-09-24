"""Values read back off a real engine in-process, in the shape a host parses.

No Nuke and no engine process. Unit tests feed the normalizer what the engine is believed to
hand back; this checks what it actually does after a run, including its serialization of lists
and of a scanned ``Sequence``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from griptape_nodes.retained_mode.events.os_events import ScanSequencesRequest, ScanSequencesResultSuccess
from griptape_nodes.retained_mode.events.parameter_events import AddParameterToNodeRequest, SetParameterValueRequest
from griptape_nodes.retained_mode.events.workflow_events import SaveWorkflowRequest, SaveWorkflowResultSuccess
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.events import (
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultSuccess,
    NukeGetParameterValuesRequest,
    NukeGetParameterValuesResultSuccess,
    NukeLoadWorkflowRequest,
    NukeLoadWorkflowResultSuccess,
    NukeSetParameterValuesRequest,
    NukeSetParameterValuesResultSuccess,
)
from nuke_host_api.handlers import (
    handle_execute_workflow,
    handle_get_parameter_values,
    handle_load_workflow,
    handle_set_parameter_values,
)
from nuke_host_api.protocol import ValueType
from tests.detached_run import settled

from .fixtures.canary.canary_workflow_builder import build_start_canary_end_flow, connect

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _add_passthrough(name: str, engine_type: str) -> None:
    for node, output in (("Start", True), ("End", False)):
        result = GriptapeNodes.handle_request(
            AddParameterToNodeRequest(
                node_name=node,
                parameter_name=name,
                default_value=None,
                tooltip="",
                type=engine_type,
                input_types=[engine_type],
                output_type=engine_type,
                mode_allowed_input=not output,
                mode_allowed_output=output,
            )
        )
        assert result.succeeded(), result
    connect("Start", name, "End", name)


async def _outputs_after_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="value_shapes")
    _add_passthrough("image", "ImageUrlArtifact")
    _add_passthrough("images", "list[ImageUrlArtifact]")
    _add_passthrough("seeds", "list[int]")
    _add_passthrough("plate", "Sequence")
    saved = GriptapeNodes.handle_request(SaveWorkflowRequest(file_name="value_shapes"))
    assert isinstance(saved, SaveWorkflowResultSuccess), saved
    loaded = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id=saved.workflow_name))
    assert isinstance(loaded, NukeLoadWorkflowResultSuccess), loaded.result_details

    frames = tmp_path / "frames"
    frames.mkdir()
    for number in (1001, 1002):
        (frames / f"frame_{number}.png").write_bytes(b"x")
    scanned = GriptapeNodes.handle_request(ScanSequencesRequest(path=str(frames / "frame_####.png")))
    assert isinstance(scanned, ScanSequencesResultSuccess), scanned
    # A host has no Sequence to send, so the scanned one is set engine-side, as a node output would be.
    result = GriptapeNodes.handle_request(
        SetParameterValueRequest(node_name="Start", parameter_name="plate", value=scanned.sequences[0])  # pyright: ignore[reportArgumentType]
    )
    assert result.succeeded(), result

    applied = await handle_set_parameter_values(
        NukeSetParameterValuesRequest(
            inputs={
                "Start": {
                    "image": {"path": str(frames / "frame_1001.png"), "format": "png"},
                    "images": [str(frames / "frame_1001.png"), str(frames / "frame_1002.png")],
                    "seeds": [42, 43],
                }
            }
        )
    )
    assert isinstance(applied, NukeSetParameterValuesResultSuccess), applied.result_details
    assert applied.rejected_inputs == []

    run = await handle_execute_workflow(NukeExecuteWorkflowRequest())
    assert isinstance(run, NukeExecuteWorkflowResultSuccess), run.result_details
    await settled()

    read = await handle_get_parameter_values(NukeGetParameterValuesRequest(sections=["outputs"]))
    assert isinstance(read, NukeGetParameterValuesResultSuccess), read.result_details
    assert read.unavailable == []
    return {"frames": frames, **read.outputs["End"]}


async def test_values_come_back_single_or_as_an_array_by_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = await _outputs_after_run(tmp_path, monkeypatch)
    frames = str(outputs["frames"]).replace("\\", "/")

    assert outputs["image"]["value"] == {"path": f"{frames}/frame_1001.png", "format": "png"}
    assert outputs["images"]["value_type"] == ValueType.IMAGE
    assert [entry["path"] for entry in outputs["images"]["value"]] == [
        f"{frames}/frame_1001.png",
        f"{frames}/frame_1002.png",
    ]
    assert outputs["seeds"] == {"value_type": ValueType.INT, "value": [42, 43], "engine_type": "list"}
    assert outputs["was_successful"]["value"] is True


async def test_a_scanned_sequence_carries_every_frame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = await _outputs_after_run(tmp_path, monkeypatch)
    frames = str(outputs["frames"]).replace("\\", "/")

    assert outputs["plate"]["value_type"] == ValueType.IMAGE
    assert [entry["path"] for entry in outputs["plate"]["value"]] == [
        f"{frames}/frame_1001.png",
        f"{frames}/frame_1002.png",
    ]
