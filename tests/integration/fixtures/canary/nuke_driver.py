"""Driver for the real-Nuke wiring check: opens the canary_workflow gizmo from a real
shot dir and runs it.

Invoked as ``nuke -t nuke_driver.py <shot_nk_path> <griptape_plugin_dir>``. Runs
inside Nuke's bundled Python (stdlib + ``nuke`` only). Opening the .nk from a real
directory (rather than an in-memory script) is the whole point: it's what makes
``nuke.script_directory()`` non-empty, which is what the outputs macro depends on.

Emits the gizmo's ``result_out`` knob value as sentinel-framed JSON on stdout so the
pytest side can parse it with ``output_protocol.extract_payload``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import nuke

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "publish_gizmo"))
from constants import versioned_node_name  # noqa: E402
from output_protocol import emit_payload  # noqa: E402

GIZMO_NODE_TYPE = versioned_node_name("canary_workflow", 1)


def main() -> None:
    if len(sys.argv) != 3:
        emit_payload(
            {
                "error": (
                    "Attempted to run nuke_driver.py. Failed due to wrong argument count: "
                    f"expected <shot_nk_path> <griptape_plugin_dir>, got {sys.argv[1:]!r}."
                )
            }
        )
        sys.exit(1)

    # Nuke's TCL layer treats a backslash as an escape, so a Windows path handed in verbatim is
    # silently mangled.
    shot_nk_path = sys.argv[1].replace("\\", "/")
    griptape_plugin_dir = sys.argv[2].replace("\\", "/")

    nuke.pluginAddPath(griptape_plugin_dir)
    # pluginAddPath alone doesn't force a directory walk; nuke.plugins() does.
    nuke.plugins(nuke.ALL, "*.gizmo")

    nuke.scriptOpen(shot_nk_path)

    node = None
    for candidate in nuke.allNodes():
        if candidate.Class() == GIZMO_NODE_TYPE:
            node = candidate
            break
    if node is None:
        emit_payload({"error": f"No {GIZMO_NODE_TYPE} node found in {shot_nk_path}"})
        sys.exit(1)

    node["run_workflow"].execute()

    emit_payload(
        {
            "output_path": node["output_path_out"].value(),
            "script_directory": nuke.script_directory(),
        }
    )


if __name__ == "__main__":
    main()
