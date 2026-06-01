from __future__ import annotations

import pytest

from nuke_runner.manifest import SCHEMA_VERSION, JobManifest, ManifestInput, ManifestOutput

# Canonical JSON from PRD §7.4
PRD_CANONICAL_JSON = """{
  "schema": "griptape-nuke-runner/1.0",
  "script": "/path/to/my_comp.nk",
  "frame_range": [1001, 1001],
  "inputs": {
    "source_image": { "path": "/tmp/gt_input_abc.png", "node": "ReadInput" }
  },
  "outputs": {
    "graded_image": { "path": "/tmp/gt_output_xyz.png", "node": "WriteOutput", "format": "png" }
  },
  "knob_overrides": [
    { "node": "Grade1", "knob": "gain", "value": 1.4 }
  ],
  "env": {
    "foundry_LICENSE": "4101@license.studio.com",
    "OCIO": "/path/to/config.ocio",
    "NEAT_VIDEO_LICENSE": "4200@license.studio.com"
  }
}"""


def test_manifest_round_trips_prd_canonical_json() -> None:
    manifest = JobManifest.from_json(PRD_CANONICAL_JSON)

    assert manifest.schema == SCHEMA_VERSION
    assert manifest.script == "/path/to/my_comp.nk"
    assert manifest.frame_range == [1001, 1001]

    assert "source_image" in manifest.inputs
    assert manifest.inputs["source_image"].path == "/tmp/gt_input_abc.png"
    assert manifest.inputs["source_image"].node == "ReadInput"

    assert "graded_image" in manifest.outputs
    assert manifest.outputs["graded_image"].path == "/tmp/gt_output_xyz.png"
    assert manifest.outputs["graded_image"].node == "WriteOutput"
    assert manifest.outputs["graded_image"].format == "png"

    assert len(manifest.knob_overrides) == 1
    assert manifest.knob_overrides[0].node == "Grade1"
    assert manifest.knob_overrides[0].knob == "gain"
    assert manifest.knob_overrides[0].value == pytest.approx(1.4)

    assert manifest.env["foundry_LICENSE"] == "4101@license.studio.com"
    assert manifest.env["OCIO"] == "/path/to/config.ocio"
    assert manifest.env["NEAT_VIDEO_LICENSE"] == "4200@license.studio.com"

    # Verify round-trip: serialise and deserialise again
    roundtripped = JobManifest.from_json(manifest.to_json())
    assert roundtripped.script == manifest.script
    assert roundtripped.inputs["source_image"].path == manifest.inputs["source_image"].path
    assert roundtripped.outputs["graded_image"].path == manifest.outputs["graded_image"].path
    assert roundtripped.knob_overrides[0].value == pytest.approx(manifest.knob_overrides[0].value)
    assert roundtripped.env == manifest.env


def test_manifest_forward_slashes_on_windows_paths() -> None:
    manifest = JobManifest(
        script="C:\\Users\\artist\\scripts\\comp.nk",
        inputs={"src": ManifestInput(path="C:\\tmp\\input.png", node="ReadInput")},
        outputs={"out": ManifestOutput(path="C:\\tmp\\output.png", node="WriteOutput")},
    )

    assert manifest.script == "C:/Users/artist/scripts/comp.nk"
    assert manifest.inputs["src"].path == "C:/tmp/input.png"
    assert manifest.outputs["out"].path == "C:/tmp/output.png"

    roundtripped = JobManifest.from_json(manifest.to_json())
    assert roundtripped.script == "C:/Users/artist/scripts/comp.nk"
    assert roundtripped.inputs["src"].path == "C:/tmp/input.png"


def test_manifest_from_json_rejects_wrong_schema_version() -> None:
    bad_json = PRD_CANONICAL_JSON.replace(SCHEMA_VERSION, "griptape-nuke-runner/0.9")
    with pytest.raises(ValueError, match="Unsupported manifest schema"):
        JobManifest.from_json(bad_json)


def test_manifest_default_output_format_is_png() -> None:
    output = ManifestOutput(path="/tmp/out.png", node="WriteNode")
    assert output.format == "png"
    assert output.type == "ImageArtifact"


def test_bake_output_path_round_trips() -> None:
    m = JobManifest(script="/tmp/test.nk", bake_output_path="/tmp/baked.nk")
    restored = JobManifest.from_json(m.to_json())
    assert restored.bake_output_path == "/tmp/baked.nk"


def test_bake_output_path_defaults_empty() -> None:
    m = JobManifest(script="/tmp/test.nk")
    assert m.bake_output_path == ""
    restored = JobManifest.from_json(m.to_json())
    assert restored.bake_output_path == ""


def test_manifest_output_path_accepts_list() -> None:
    output = ManifestOutput(path=["/tmp/f.0001.exr", "/tmp/f.0002.exr"], node="Write1", type="ImageSequenceArtifact")
    assert isinstance(output.path, list)
    assert output.path == ["/tmp/f.0001.exr", "/tmp/f.0002.exr"]


def test_manifest_output_list_path_round_trips_json() -> None:
    m = JobManifest(
        script="/tmp/test.nk",
        outputs={
            "frames": ManifestOutput(
                path=["/tmp/f.0001.exr", "/tmp/f.0002.exr"],
                node="Write1",
                type="ImageSequenceArtifact",
            )
        },
    )
    restored = JobManifest.from_json(m.to_json())
    assert restored.outputs["frames"].path == ["/tmp/f.0001.exr", "/tmp/f.0002.exr"]


def test_manifest_output_list_path_normalises_backslashes() -> None:
    output = ManifestOutput(
        path=["C:\\tmp\\f.0001.exr", "C:\\tmp\\f.0002.exr"],
        node="Write1",
        type="ImageSequenceArtifact",
    )
    assert output.path == ["C:/tmp/f.0001.exr", "C:/tmp/f.0002.exr"]


def test_manifest_output_str_path_normalisation_unchanged() -> None:
    output = ManifestOutput(path="C:\\tmp\\out.png", node="WriteNode")
    assert output.path == "C:/tmp/out.png"
