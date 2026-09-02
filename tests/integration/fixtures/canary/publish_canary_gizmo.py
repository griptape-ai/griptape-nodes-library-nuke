"""Publish the canary workflow gizmo for the real-Nuke wiring check's ``.nk`` fixture generator.

Step 1 of regenerating ``tests/integration/fixtures/canary/canary_workflow.nk``. Run in
this repo's own venv (needs ``griptape_nodes``, unavailable inside Nuke's bundled Python):

    uv run python -m tests.integration.fixtures.canary.publish_canary_gizmo --install-dir /tmp/canary_gizmo_fixture

Run that from the repository root: ``-m`` puts the current directory on ``sys.path``, which
is what lets both the ``tests.*`` package chain and the ``publish_gizmo.*`` imports resolve.

Then feed the printed ``griptape`` plugin dir to step 2, ``nuke -t
scripts/generate_test_fixtures.py``, via the ``CANARY_GIZMO_INSTALL_DIR`` env var:

    CANARY_GIZMO_INSTALL_DIR=/tmp/canary_gizmo_fixture/install/griptape /path/to/Nuke -t scripts/generate_test_fixtures.py

The published bundle itself is never committed -- only the resulting ``.nk``. See
that script's module docstring for why the gizmo must exist before Nuke can
reference it in a saved script.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .canary_workflow_builder import GIZMO_NODE_NAME, publish_canary_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", required=True, help="Directory to publish the gizmo into")
    args = parser.parse_args()

    install_dir = Path(args.install_dir)
    bundle = publish_canary_bundle(workspace=install_dir / "workspace", install_dir=install_dir / "install")

    print(f"Published gizmo node type: {GIZMO_NODE_NAME}")
    print(f"Companion dir: {bundle.companion_base}")
    print(f"Griptape plugin dir (pass to step 2): {bundle.griptape_dir}")


if __name__ == "__main__":
    main()
