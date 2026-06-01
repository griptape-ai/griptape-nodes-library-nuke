"""Unit tests for nuke_runner/runner.py — nuke module mocked out."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Mock the nuke module before any import of runner
sys.modules.setdefault("nuke", MagicMock())

_nuke: Any = sys.modules["nuke"]


def _run_main(manifest: dict, tmp_path: Path) -> dict:
    """Write manifest to disk, call main(), return parsed output manifest."""
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "output.json"
    manifest_path.write_text(json.dumps(manifest))

    from nuke_runner.runner import main

    with patch("sys.argv", ["runner.py", "--manifest", str(manifest_path), "--output-manifest", str(output_path)]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 0, f"runner exited non-zero: {output_path.read_text()}"
    return json.loads(output_path.read_text())


def _base_manifest(outputs: dict | None = None) -> dict:
    return {
        "schema": "griptape-nuke-runner/1.0",
        "script": "/fake/comp.nk",
        "frame_range": [1001, 1001],
        "inputs": {},
        "outputs": outputs or {},
        "knob_overrides": [],
        "env": {},
        "bake_output_path": "",
    }


class TestExecuteTypes:
    def test_contains_video_url_artifact(self) -> None:
        from nuke_runner.runner import _EXECUTE_TYPES

        assert "VideoUrlArtifact" in _EXECUTE_TYPES

    def test_contains_image_sequence_artifact(self) -> None:
        from nuke_runner.runner import _EXECUTE_TYPES

        assert "ImageSequenceArtifact" in _EXECUTE_TYPES

    def test_contains_image_artifact(self) -> None:
        from nuke_runner.runner import _EXECUTE_TYPES

        assert "ImageArtifact" in _EXECUTE_TYPES


class TestVideoUrlArtifactOutput:
    def test_writes_string_path_for_video(self, tmp_path: Path) -> None:
        out_file = tmp_path / "render.mp4"
        out_file.write_bytes(b"")

        manifest = _base_manifest(
            outputs={"clip": {"path": str(out_file), "node": "Write1", "type": "VideoUrlArtifact"}}
        )

        _nuke.scriptOpen = MagicMock()
        _nuke.root.return_value = MagicMock()
        _nuke.root.return_value.__getitem__ = MagicMock(return_value=MagicMock())
        _nuke.toNode.return_value = MagicMock()
        _nuke.execute = MagicMock()

        result = _run_main(manifest, tmp_path)
        assert result["outputs"]["clip"] == str(out_file).replace("\\", "/")


class TestNonExecutableArtifactSkipped:
    def test_unknown_type_not_in_outputs(self, tmp_path: Path) -> None:
        manifest = _base_manifest(
            outputs={"cam": {"path": "/tmp/cam.json", "node": "Camera1", "type": "CameraMatrixArtifact"}}
        )

        _nuke.scriptOpen = MagicMock()
        _nuke.root.return_value = MagicMock()
        _nuke.root.return_value.__getitem__ = MagicMock(return_value=MagicMock())
        _nuke.toNode = MagicMock()
        _nuke.execute = MagicMock()

        result = _run_main(manifest, tmp_path)
        assert "cam" not in result["outputs"]
        _nuke.execute.assert_not_called()


class TestImageSequenceArtifactOutput:
    def test_globs_rendered_frames_and_writes_list(self, tmp_path: Path) -> None:
        seq_dir = tmp_path / "seq"
        seq_dir.mkdir()
        pattern = str(seq_dir / "frame.%04d.png")

        # Create fake rendered frame files
        (seq_dir / "frame.1001.png").write_bytes(b"\x89PNG")
        (seq_dir / "frame.1002.png").write_bytes(b"\x89PNG")

        manifest = _base_manifest(
            outputs={"frames": {"path": pattern, "node": "Write1", "type": "ImageSequenceArtifact"}}
        )

        _nuke.scriptOpen = MagicMock()
        _nuke.root.return_value = MagicMock()
        _nuke.root.return_value.__getitem__ = MagicMock(return_value=MagicMock())
        _nuke.toNode.return_value = MagicMock()
        _nuke.execute = MagicMock()

        result = _run_main(manifest, tmp_path)
        frames = result["outputs"]["frames"]
        assert isinstance(frames, list)
        assert len(frames) == 2
        assert all("frame." in p for p in frames)

    def test_empty_glob_writes_empty_list(self, tmp_path: Path) -> None:
        seq_dir = tmp_path / "emptyseq"
        seq_dir.mkdir()
        pattern = str(seq_dir / "frame.%04d.png")

        manifest = _base_manifest(
            outputs={"frames": {"path": pattern, "node": "Write1", "type": "ImageSequenceArtifact"}}
        )

        _nuke.scriptOpen = MagicMock()
        _nuke.root.return_value = MagicMock()
        _nuke.root.return_value.__getitem__ = MagicMock(return_value=MagicMock())
        _nuke.toNode.return_value = MagicMock()
        _nuke.execute = MagicMock()

        result = _run_main(manifest, tmp_path)
        frames = result["outputs"]["frames"]
        assert isinstance(frames, list)
        assert frames == []
