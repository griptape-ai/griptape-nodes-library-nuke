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
        "schema": "griptape-nuke-runner/1.2",
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

    def test_contains_sequence(self) -> None:
        from nuke_runner.runner import _EXECUTE_TYPES

        assert "Sequence" in _EXECUTE_TYPES

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


class TestSequenceOutput:
    def test_writes_pattern_path_for_sequence(self, tmp_path: Path) -> None:
        seq_dir = tmp_path / "seq"
        seq_dir.mkdir()
        pattern = str(seq_dir / "frame_####.png")

        manifest = _base_manifest(outputs={"frames": {"path": pattern, "node": "Write1", "type": "Sequence"}})

        _nuke.scriptOpen = MagicMock()
        _nuke.root.return_value = MagicMock()
        _nuke.root.return_value.__getitem__ = MagicMock(return_value=MagicMock())
        _nuke.toNode.return_value = MagicMock()
        _nuke.execute = MagicMock()

        result = _run_main(manifest, tmp_path)
        assert result["outputs"]["frames"] == pattern.replace("\\", "/")


class _FakeKnob:
    """Stands in for a plain File_Knob, which has no fromUserText."""

    def __init__(self) -> None:
        self.value: Any = None
        self.user_text: str | None = None

    def setValue(self, value: Any) -> None:  # noqa: N802
        self.value = value


class _FakeReadFileKnob(_FakeKnob):
    def fromUserText(self, text: str) -> None:  # noqa: N802
        self.user_text = text


class _FakeReadNode:
    def __init__(self, *, user_text: bool = True, range_knobs: bool = True) -> None:
        file_knob = _FakeReadFileKnob() if user_text else _FakeKnob()
        self.knobs: dict[str, _FakeKnob] = {"file": file_knob}
        if range_knobs:
            for name in ("first", "last", "origfirst", "origlast"):
                self.knobs[name] = _FakeKnob()

    def __getitem__(self, name: str) -> _FakeKnob:
        return self.knobs[name]

    def knob(self, name: str) -> _FakeKnob | None:
        return self.knobs.get(name)


class TestSetInputFile:
    def test_sequence_range_goes_through_from_user_text(self) -> None:
        from nuke_runner.read_input import set_input_file

        node = _FakeReadNode()
        set_input_file(node, "/plates/bg.####.exr", 1001, 1048)

        assert node["file"].user_text == "/plates/bg.####.exr 1001-1048"
        assert node["file"].value is None

    def test_single_file_input_uses_set_value(self) -> None:
        from nuke_runner.read_input import set_input_file

        node = _FakeReadNode()
        set_input_file(node, "/tmp/plate.png", None, None)

        assert node["file"].value == "/tmp/plate.png"
        assert node["file"].user_text is None

    def test_path_containing_space_falls_back_to_explicit_knobs(self) -> None:
        """A space makes '<path> <first>-<last>' ambiguous, so the range is set knob by knob."""
        from nuke_runner.read_input import set_input_file

        node = _FakeReadNode()
        set_input_file(node, "/Volumes/My Show/bg.####.exr", 1001, 1048)

        assert node["file"].user_text is None
        assert node["file"].value == "/Volumes/My Show/bg.####.exr"
        assert node["first"].value == 1001
        assert node["last"].value == 1048

    def test_knob_without_from_user_text_sets_orig_range_too(self) -> None:
        from nuke_runner.read_input import set_input_file

        node = _FakeReadNode(user_text=False)
        set_input_file(node, "/plates/bg.####.exr", 1001, 1048)

        assert node["file"].value == "/plates/bg.####.exr"
        assert node["origfirst"].value == 1001
        assert node["origlast"].value == 1048

    def test_missing_range_knobs_do_not_raise(self) -> None:
        from nuke_runner.read_input import set_input_file

        node = _FakeReadNode(user_text=False, range_knobs=False)
        set_input_file(node, "/plates/bg.####.exr", 1001, 1048)

        assert node["file"].value == "/plates/bg.####.exr"


class TestBakerInputs:
    def test_sequence_input_range_is_applied_before_saving(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.json"
        output_path = tmp_path / "output.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "script": "/fake/comp.nk",
                    "inputs": {
                        "plate": {"path": "/plates/bg.####.exr", "node": "ReadPlate", "first": 1001, "last": 1048}
                    },
                    "knob_overrides": [],
                    "bake_output_path": str(tmp_path / "baked.nk"),
                }
            )
        )
        read_node = _FakeReadNode()
        _nuke.scriptOpen = MagicMock()
        _nuke.scriptSaveAs = MagicMock()
        _nuke.toNode.return_value = read_node

        from nuke_runner.baker import main

        with patch("sys.argv", ["baker.py", "--manifest", str(manifest_path), "--output-manifest", str(output_path)]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        assert read_node["file"].user_text == "/plates/bg.####.exr 1001-1048"
