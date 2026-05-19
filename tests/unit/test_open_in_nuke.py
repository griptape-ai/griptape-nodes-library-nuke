from __future__ import annotations

import json
import os

from nuke_nodes.nuke_script_node import _build_open_in_nuke_launch
from nuke_runner.manifest import KnobOverride


def test_command_does_not_use_t_flag() -> None:
    cmd, _ = _build_open_in_nuke_launch("/usr/bin/nuke", "/comp/shot.nk", [], {})
    assert "-t" not in cmd


def test_command_includes_p_flag_and_startup_script() -> None:
    cmd, _ = _build_open_in_nuke_launch("/usr/bin/nuke", "/comp/shot.nk", [], {})
    assert cmd[0] == "/usr/bin/nuke"
    assert "-p" in cmd
    p_idx = cmd.index("-p")
    startup = cmd[p_idx + 1]
    assert startup.endswith(".py")
    assert os.path.exists(startup)
    # .nk path must NOT be a CLI arg — it is baked into the startup script body
    assert "/comp/shot.nk" not in cmd


def test_startup_script_calls_script_open() -> None:
    cmd, _ = _build_open_in_nuke_launch("/usr/bin/nuke", "/comp/shot.nk", [], {})
    startup_path = cmd[cmd.index("-p") + 1]
    with open(startup_path, encoding="utf-8") as f:
        src = f.read()
    assert "nuke.scriptOpen(" in src
    assert "/comp/shot.nk" in src


def test_startup_script_contains_manifest_path() -> None:
    cmd, _ = _build_open_in_nuke_launch("/usr/bin/nuke", "/comp/shot.nk", [], {})
    startup_path = cmd[cmd.index("-p") + 1]
    with open(startup_path, encoding="utf-8") as f:
        src = f.read()
    # The manifest path must appear as a Python string literal in the startup script
    assert "open(" in src
    assert ".json" in src


def test_overrides_serialised_to_manifest() -> None:
    overrides = [
        KnobOverride(node="Grade1", knob="gain", value=1.4),
        KnobOverride(node="Grade1", knob="gamma", value=0.9),
    ]
    cmd, _ = _build_open_in_nuke_launch("/usr/bin/nuke", "/comp/shot.nk", overrides, {})

    # Find the manifest file path from the startup script source
    startup_path = cmd[cmd.index("-p") + 1]
    with open(startup_path, encoding="utf-8") as f:
        src = f.read()
    # Extract the quoted path from the open() call in the startup script
    import re

    match = re.search(r"open\((['\"][^'\"]+['\"])", src)
    assert match, "could not find open() path in startup script"
    manifest_path = match.group(1).strip("'\"")

    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["knob_overrides"] == [
        {"node": "Grade1", "knob": "gain", "value": 1.4},
        {"node": "Grade1", "knob": "gamma", "value": 0.9},
    ]


def test_empty_overrides_produces_empty_array() -> None:
    cmd, _ = _build_open_in_nuke_launch("/usr/bin/nuke", "/comp/shot.nk", [], {})
    startup_path = cmd[cmd.index("-p") + 1]
    with open(startup_path, encoding="utf-8") as f:
        src = f.read()
    import re

    match = re.search(r"open\((['\"][^'\"]+['\"])", src)
    assert match
    manifest_path = match.group(1).strip("'\"")
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["knob_overrides"] == []
