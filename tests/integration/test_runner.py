from __future__ import annotations

import os
import pathlib

import pytest

from execution.direct import DirectSubprocessProvider
from nuke_runner.manifest import JobManifest, ManifestOutput

NUKE_EXE = os.environ.get("NUKE_EXECUTABLE")
RUNNER = os.path.join(os.path.dirname(__file__), "..", "..", "nuke_runner", "runner.py")
FIXTURE = os.path.join(os.path.dirname(__file__), "..", "unit", "fixtures", "constant_write.nk")

pytestmark = pytest.mark.skipif(not NUKE_EXE, reason="NUKE_EXECUTABLE not set")


def test_runner_executes_constant_write_node_and_produces_output(tmp_path: pathlib.Path) -> None:
    assert NUKE_EXE is not None
    out_path = str(tmp_path / "output.png")
    manifest = JobManifest(
        script=os.path.abspath(FIXTURE),
        outputs={"result": ManifestOutput(path=out_path, node="ConstantOutput")},
        frame_range=[1, 1],
    )
    provider = DirectSubprocessProvider(nuke_exe=NUKE_EXE, runner_script=os.path.abspath(RUNNER))
    handle = provider.submit(manifest)
    result = provider.result(handle)

    assert result.return_code == 0, f"runner exited {result.return_code}"
    assert result.outputs.get("result") == out_path
    assert os.path.exists(out_path), "output PNG was not written"
