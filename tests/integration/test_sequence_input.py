"""Verifies a frame sequence passed into a Nuke script is read across its whole range."""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

from execution.direct import DirectSubprocessProvider
from nuke_runner.manifest import JobManifest, ManifestInput, ManifestOutput

NUKE_EXE = os.environ.get("NUKE_EXECUTABLE")
_HERE = os.path.dirname(__file__)
RUNNER = os.path.normpath(os.path.join(_HERE, "..", "..", "nuke_runner", "runner.py"))
BUILDER = os.path.normpath(os.path.join(_HERE, "fixtures", "build_sequence_fixture.py"))

pytestmark = pytest.mark.skipif(not NUKE_EXE, reason="NUKE_EXECUTABLE not set")

LAST_FRAME = 5


@pytest.fixture
def sequence_script(tmp_path: pathlib.Path) -> tuple[str, str]:
    """Build a .nk via Nuke itself; returns (script path, frames dir)."""
    assert NUKE_EXE is not None
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    script_out = tmp_path / "seq_comp.nk"
    frames_arg = str(frames_dir).replace("\\", "/")
    script_arg = str(script_out).replace("\\", "/")
    result = subprocess.run(  # noqa: S603
        [
            NUKE_EXE,
            "-t",
            BUILDER,
            # nuke -t claims a bare numeric argument as a frame range and drops it before
            # sys.argv reaches the script, so "--last", "5" arrives as "--last" alone.
            # The = form keeps the value attached.
            f"--frames-dir={frames_arg}",
            f"--script-out={script_arg}",
            f"--last={LAST_FRAME}",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"fixture build exited {result.returncode}:\n{result.stderr}"
    assert script_out.is_file(), "fixture .nk was not saved"
    rendered = sorted(frames_dir.glob("plate.*.png"))
    assert len(rendered) == LAST_FRAME, f"expected {LAST_FRAME} source frames, got {len(rendered)}"
    return str(script_out), str(frames_dir)


def _run(script: str, frames_dir: str, out_dir: pathlib.Path, first: int | None, last: int | None):
    assert NUKE_EXE is not None
    manifest = JobManifest(
        script=script,
        inputs={
            "plate": ManifestInput(
                path=f"{frames_dir}/plate.%04d.png".replace("\\", "/"),
                node="ReadPlate",
                first=first,
                last=last,
            )
        },
        outputs={
            "result": ManifestOutput(
                path=str(out_dir / "out.%04d.png").replace("\\", "/"),
                node="WriteOut",
                type="Sequence",
            )
        },
        frame_range=[1, LAST_FRAME],
    )
    provider = DirectSubprocessProvider(nuke_exe=NUKE_EXE, runner_script=RUNNER)
    return provider.result(provider.submit(manifest))


def test_sequence_input_renders_every_frame_distinctly(
    sequence_script: tuple[str, str], tmp_path: pathlib.Path
) -> None:
    """The authored range is 1-1, so a Read stuck on it repeats frame 1 across the render."""
    script, frames_dir = sequence_script
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = _run(script, frames_dir, out_dir, first=1, last=LAST_FRAME)
    assert result.return_code == 0, f"runner exited {result.return_code}:\n" + "\n".join(result.log[-20:])

    written = sorted(out_dir.glob("out.*.png"))
    assert len(written) == LAST_FRAME, f"expected {LAST_FRAME} output frames, got {len(written)}"
    digests = {p.read_bytes() for p in written}
    assert len(digests) == LAST_FRAME, (
        "output frames are not all distinct — the Read node did not advance past its authored range"
    )


def test_sequence_input_path_containing_space_still_carries_its_range(
    sequence_script: tuple[str, str], tmp_path: pathlib.Path
) -> None:
    """A space defeats the '<path> <first>-<last>' form, so the explicit-knob branch runs."""
    script, frames_dir = sequence_script
    spaced_dir = tmp_path / "My Show"
    spaced_dir.mkdir()
    for frame in pathlib.Path(frames_dir).glob("plate.*.png"):
        (spaced_dir / frame.name).write_bytes(frame.read_bytes())
    out_dir = tmp_path / "out_spaced"
    out_dir.mkdir()

    result = _run(script, str(spaced_dir), out_dir, first=1, last=LAST_FRAME)
    assert result.return_code == 0, f"runner exited {result.return_code}:\n" + "\n".join(result.log[-20:])

    written = sorted(out_dir.glob("out.*.png"))
    assert len(written) == LAST_FRAME
    digests = {p.read_bytes() for p in written}
    assert len(digests) == LAST_FRAME, "a path with a space lost its frame range"


def test_single_file_input_without_range_still_loads(sequence_script: tuple[str, str], tmp_path: pathlib.Path) -> None:
    """An input carrying no range must keep working exactly as before."""
    script, frames_dir = sequence_script
    out_dir = tmp_path / "out_single"
    out_dir.mkdir()

    result = _run(script, frames_dir, out_dir, first=None, last=None)
    assert result.return_code == 0, f"runner exited {result.return_code}:\n" + "\n".join(result.log[-20:])
    assert list(out_dir.glob("out.*.png")), "no output written for a rangeless input"
