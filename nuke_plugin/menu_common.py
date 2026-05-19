"""Shared Nuke menu registration — imported by each per-version menu.py shim."""

from __future__ import annotations

import os
import sys

_plugin_dir = os.path.dirname(os.path.abspath(__file__))
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from griptape_annotator_panel import register  # noqa: E402

register()
