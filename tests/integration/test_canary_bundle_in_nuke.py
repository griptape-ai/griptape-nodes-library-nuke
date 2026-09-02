"""A real Nuke wiring check for the workspace-not-moved fix.

Publishes the canary workflow gizmo (fresh, at test time) into a tmp install dir,
copies the committed ``fixtures/canary/canary_workflow.nk`` (containing one
``canary_workflow_v01`` instance) into a tmp shot dir, and drives it through a real
``nuke -t`` process. test_canary_bundle.py is the load-bearing regression
signal; this test only guards the Nuke-side wiring -- pluginAddPath, gizmo class
name, script_directory()-driven outputs -- that test_canary_bundle.py can't
reach.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from publish_gizmo.output_protocol import extract_payload

if TYPE_CHECKING:
    from collections.abc import Callable

    from .fixtures.canary.canary_workflow_builder import PublishedBundle

NUKE_EXE = os.environ.get("NUKE_EXECUTABLE")
pytestmark = pytest.mark.skipif(not NUKE_EXE, reason="NUKE_EXECUTABLE not set")

FIXTURE_NK = Path(__file__).parent / "fixtures" / "canary" / "canary_workflow.nk"
DRIVER = Path(__file__).parent / "fixtures" / "canary" / "nuke_driver.py"


def test_gizmo_writes_outputs_beside_nk_script_via_real_nuke(
    published_bundle: Callable[..., PublishedBundle],
    xdg_scoped_env: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> None:
    assert NUKE_EXE is not None
    bundle = published_bundle()

    shot_dir = tmp_path / "shot"
    shot_dir.mkdir()
    shot_nk = shot_dir / "canary_workflow.nk"
    shutil.copy(FIXTURE_NK, shot_nk)

    result = subprocess.run(  # noqa: S603
        [NUKE_EXE, "-t", str(DRIVER), str(shot_nk), str(bundle.griptape_dir)],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
        # Without a scoped XDG_DATA_HOME the gizmo's run button builds its uv venv under the
        # developer's real ~/.local/share, a fresh ~250-package tree per run that nothing deletes.
        env=xdg_scoped_env(),
    )

    diagnostic = f"exit={result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    assert result.returncode == 0, diagnostic

    payload = extract_payload(result.stdout)
    assert payload["script_directory"], diagnostic
    assert Path(payload["script_directory"]).samefile(shot_dir), diagnostic

    written = list((shot_dir / "griptape_outputs").glob("*.txt"))
    assert len(written) == 1, diagnostic

    reported_path = Path(payload["output_path"])
    assert reported_path.is_absolute(), diagnostic
    assert reported_path.samefile(written[0]), diagnostic
