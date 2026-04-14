"""Nuke gizmo 'Run Workflow' button logic.

This file is shipped into the companion directory alongside the workflow bundle.
The gizmo's PyScript_Knob contains only a short bootstrap that loads and execs
this file, passing a ``_config`` dict with workflow-specific values. That keeps
the TCL-escaped content in the gizmo minimal and this logic independently
readable and testable.

``_config`` keys (all injected by the bootstrap at publish time):
    workflow_filename (str): basename of the workflow .json/.py file
    start_node_name (str): name of the NukeStartFlow node
    param_names (list[str]): ordered list of input knob names
    media_input_names (list[str]): input param names that are media types
    media_output_names (list[str]): output param names that are media types
    media_input_index_map (dict[str,int]): media input name -> Input node index
    media_output_read_map (dict[str,str]): media output name -> internal Read node name
    input_node_prefix (str): prefix for internal Input node names (e.g. "Input")
    temp_file_prefix (str): prefix for temp render files (e.g. "gt_input")
    versioned (bool): True when the gizmo uses the versioned layout (v1/, v2/, etc.)

This module runs inside Nuke's Python interpreter (stdlib only — no third-party
packages available). ``nuke`` is already in scope when exec'd from the gizmo.
"""

import json
import os
import platform
import shutil
import subprocess
import tempfile

# _config is injected by the gizmo bootstrap before this file is exec'd.
# globals().get reads the injected value when present; falls back to {} otherwise.
_config: dict = globals().get("_config", {})

_workflow_filename: str = _config.get("workflow_filename", "")
_start_node_name: str = _config.get("start_node_name", "")
_param_names: list = _config.get("param_names", [])
_media_input_names: list = _config.get("media_input_names", [])
_media_output_names: list = _config.get("media_output_names", [])
_media_input_index_map: dict = _config.get("media_input_index_map", {})
_media_output_read_map: dict = _config.get("media_output_read_map", {})
_input_node_prefix: str = _config.get("input_node_prefix", "Input")
_temp_file_prefix: str = _config.get("temp_file_prefix", "gt_input")

# -- Resolve paths from the gizmo node --

node = nuke.thisNode()  # noqa: F821  # 'nuke' is in scope when exec'd from the gizmo

# _companion_dir is resolved by the bootstrap before this file is exec'd.
# By the time we get here it should be set, but guard against stale .nk values
# (absolute path from a different machine that no longer exists on disk).
companion = node["_companion_dir"].value()
if not companion or not os.path.isdir(companion):
    raise RuntimeError(
        f"Griptape: companion directory not found: {companion!r}. "
        "Re-publish the gizmo or ensure griptape_gizmos/ is in the same directory as the .gizmo file."
    )

# Versioned gizmos store each workflow file in a version subdir (v1/, v2/, ...).
# The griptape_version knob on the node controls which version is run.
# Unversioned gizmos (published before this feature) store the workflow directly in companion.
if _config.get("versioned") and node.knob("griptape_version"):
    _selected_version = node["griptape_version"].value()
    workflow_file = os.path.join(companion, _selected_version, _workflow_filename)
else:
    workflow_file = os.path.join(companion, _workflow_filename)

runner = os.path.join(companion, "run_workflow.py")

# Populate output_dir from the companion if the knob is empty (first run on a shared gizmo).
output_dir = node["output_dir"].value()
if not output_dir:
    output_dir = os.path.join(companion, "outputs")
    node["output_dir"].setValue(output_dir)

# -- Node error state helpers --
# Tile color values: 0xff9900ff = Griptape orange (default), 0xff0000ff = red (error)
_DEFAULT_TILE_COLOR = 0xFF9900FF
_ERROR_TILE_COLOR = 0xFF0000FF


def _set_node_error(message: str) -> None:
    """Mark the gizmo tile red and show a short error label."""
    node["tile_color"].setValue(_ERROR_TILE_COLOR)
    node["label"].setValue("[ERROR]\n" + message[:120])
    nuke.error(message)  # noqa: F821


def _clear_node_error() -> None:
    """Restore the gizmo to its default (non-error) appearance."""
    node["tile_color"].setValue(_DEFAULT_TILE_COLOR)
    node["label"].setValue("")


# -- Collect input values from knobs --

inputs: dict = {}
for _k in _param_names:
    if node.knob(_k):
        inputs[_k] = node[_k].value()

# -- Render media inputs from upstream Nuke connections to temp files --

for _mk in _media_input_names:
    _input_idx = _media_input_index_map[_mk]
    if node.input(_input_idx) is not None:
        _tmp = os.path.join(
            tempfile.gettempdir(),
            f"{_temp_file_prefix}_{node.name()}_{_mk}_{int(nuke.frame())}.jpg",  # noqa: F821
        )
        node.begin()
        try:
            _in = nuke.toNode(f"{_input_node_prefix}{_input_idx + 1}")  # noqa: F821
            _w = nuke.nodes.Write(name="_GT_TMP_WRITE")  # noqa: F821
            _w["file"].setValue(_tmp)
            _w["file_type"].setValue("jpg")
            _w.setInput(0, _in)
            nuke.execute(_w, int(nuke.frame()), int(nuke.frame()))  # noqa: F821
            nuke.delete(_w)  # noqa: F821
        finally:
            node.end()
        inputs[_mk] = _tmp

# -- Locate uv, installing it if absent --

flow_input = json.dumps({_start_node_name: inputs})

uv = shutil.which("uv")
if not uv:
    _fallbacks = [os.path.expanduser("~/.local/bin/uv"), os.path.expanduser("~/.cargo/bin/uv")]
    if platform.system() == "Windows":
        _lappdata = os.environ.get("LOCALAPPDATA", "")
        if _lappdata:
            _fallbacks.append(os.path.join(_lappdata, "uv", "uv.exe"))
    for _p in _fallbacks:
        if os.path.isfile(_p):
            uv = _p
            break

if not uv:
    if platform.system() == "Windows":
        _install = subprocess.run(
            ["powershell", "-Command", "irm https://astral.sh/uv/install.ps1 | iex"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    else:
        _install = subprocess.run(
            ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    if _install.returncode == 0:
        _fallbacks = [os.path.expanduser("~/.local/bin/uv"), os.path.expanduser("~/.cargo/bin/uv")]
        if platform.system() == "Windows":
            _lappdata = os.environ.get("LOCALAPPDATA", "")
            if _lappdata:
                _fallbacks.append(os.path.join(_lappdata, "uv", "uv.exe"))
        for _p in _fallbacks:
            if os.path.isfile(_p):
                uv = _p
                break
    else:
        msg = (
            "Failed to install uv automatically.\n"
            "Install it manually: https://docs.astral.sh/uv/getting-started/installation/\n"
            "Then restart Nuke."
        )
        nuke.message(msg)  # noqa: F821
        _set_node_error(msg)

# -- Run the workflow via uv --

if uv:
    cmd = [
        uv,
        "run",
        "--project",
        companion,
        "python",
        runner,
        "--workflow-file",
        workflow_file,
        "--json-input",
        flow_input,
        "--output-dir",
        output_dir,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=companion, timeout=600)
    if result.returncode == 0:
        try:
            output = json.loads(result.stdout.strip())
            for _k, _v in output.items():
                if node.knob(_k):
                    node[_k].setValue(str(_v))
            # Display each media output in its corresponding internal Read node
            for _mk in _media_output_names:
                _mv = output.get(_mk, "")
                if _mv and os.path.isfile(str(_mv)):
                    _read_name = _media_output_read_map.get(_mk)
                    if _read_name:
                        try:
                            node.begin()
                            _r = nuke.toNode(_read_name)  # noqa: F821
                            if _r:
                                _r["file"].setValue(str(_mv))
                                try:
                                    _r["reload"].execute()
                                except Exception:
                                    pass
                        finally:
                            node.end()
            nuke.updateUI()  # noqa: F821
            _clear_node_error()
            nuke.message("Workflow completed!")  # noqa: F821
        except Exception as _e:
            error_message = "Error parsing output: " + str(_e) + "\n" + result.stdout[:300]
            nuke.message(error_message)  # noqa: F821
            _set_node_error(error_message)
    else:
        full_error = "Workflow failed. Logs below:\n" + result.stderr
        nuke.message("Workflow failed:\n" + result.stderr[-2000:])  # noqa: F821
        _set_node_error(full_error)
