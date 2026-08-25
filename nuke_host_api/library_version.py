"""The version this library actually ships, read from its own manifest.

protocol.py previously carried a hardcoded LIBRARY_VERSION, a third copy of this value
alongside pyproject.toml's, and the two had already drifted (0.1.0 vs the manifest's
0.3.0). The manifest is what the engine registers and what a user actually installs, so it
is the one authoritative source.
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path

logger = logging.getLogger("griptape_nodes")

# Resolved relative to this file, not the process working directory, since a host may
# launch the engine from anywhere.
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "griptape-nodes-library.json"


@functools.lru_cache(maxsize=1)
def version() -> str:
    """Return the shipped library version, or "unknown" when the manifest cannot be read.

    Cached, since the manifest does not change while the process is running.
    """
    try:
        manifest = json.loads(MANIFEST_PATH.read_text())
        return str(manifest["metadata"]["library_version"])
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("Could not read library_version from %s", MANIFEST_PATH)
        return "unknown"


def reset() -> None:
    """Drop the cached read.

    Called when the library unregisters. A library reload without a process restart is a
    real, handled scenario, and an in-place upgrade must not keep serving the pre-upgrade
    version to a host that connects after the reload.
    """
    version.cache_clear()
