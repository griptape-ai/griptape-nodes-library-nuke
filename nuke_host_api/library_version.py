"""Read the installed library version from the engine's manifest."""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path

logger = logging.getLogger("griptape_nodes")

# Resolve from the package rather than the caller's working directory.
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "griptape-nodes-library.json"


@functools.lru_cache(maxsize=1)
def version() -> str:
    """Return the cached manifest version or ``unknown`` when unreadable."""
    try:
        manifest = json.loads(MANIFEST_PATH.read_text())
        return str(manifest["metadata"]["library_version"])
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("Could not read library_version from %s", MANIFEST_PATH)
        return "unknown"


def reset() -> None:
    """Clear the cache because library reloads do not require process restarts."""
    version.cache_clear()
