"""Utility functions for locating and installing the Griptape Annotator plugin.

This module is importable from Griptape-side code (Python 3.12) and does not
depend on Nuke or any third-party package.
"""

from __future__ import annotations

from pathlib import Path

_PLUGIN_DIR = Path(__file__).parent


def get_plugin_path(nuke_major: int) -> Path:
    """Return the nuke_plugin subdirectory for *nuke_major*.

    Falls back to the highest available version ≤ nuke_major when an exact
    match is not present. Raises RuntimeError if nothing is found.
    """
    candidate = _PLUGIN_DIR / f"nuke{nuke_major}"
    if candidate.exists():
        return candidate

    available = sorted(
        int(d.name.replace("nuke", ""))
        for d in _PLUGIN_DIR.glob("nuke*")
        if d.is_dir() and d.name.replace("nuke", "").isdigit()
    )
    best = max((v for v in available if v <= nuke_major), default=None)
    if best is None:
        raise RuntimeError(
            f"No Griptape Annotator plugin available for Nuke {nuke_major} or earlier. Available versions: {available}"
        )
    return _PLUGIN_DIR / f"nuke{best}"
