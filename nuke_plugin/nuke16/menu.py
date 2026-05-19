"""Nuke 16 menu hook — registers the Griptape Annotator panel.

Nuke auto-executes menu.py files found on NUKE_PATH at startup.
"""

import os
import sys

_plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from menu_common import *  # noqa: F401, F403, E402
