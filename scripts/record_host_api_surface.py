#!/usr/bin/env python3
"""Record the current wire surface as a frozen snapshot.

Run this only when introducing a NEW protocol version:

    python scripts/record_host_api_surface.py

It refuses to overwrite an existing snapshot. A recorded version is a promise to every
plugin already compiled against it, and the whole point of the guard is that the promise
cannot be edited away to make a test pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.unit.host_api_surface import capture_surface  # noqa: E402

FROZEN_DIR = REPO_ROOT / "tests" / "unit" / "fixtures" / "host_api"


def main() -> int:
    surface = capture_surface()
    version = surface["protocol_version"]
    destination = FROZEN_DIR / f"protocol_v{version}.json"

    if destination.exists():
        print(f"Refusing to overwrite {destination.name}.")
        print()
        print(f"Protocol v{version} is already recorded. To make a breaking change, bump")
        print("PROTOCOL_VERSION in protocol.py and run this again, keeping the old snapshot")
        print("so plugins speaking the old version stay covered.")
        # Deleting this file to get past the check is not a loophole, it is removing the
        # guard. The snapshot exists to fail loudly on exactly that kind of change.
        return 1

    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(surface, indent=2, sort_keys=True) + "\n")
    print(f"Recorded protocol v{version} -> {destination}")
    print(
        f"  {len(surface['verbs'])} verbs, {len(surface['notifications'])} notifications, "
        f"{len(surface['payloads'])} payloads"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
