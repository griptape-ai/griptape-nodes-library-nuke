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
    version (str): version string, e.g. "v1". The workflow file is resolved as
        ``companion/<version>/workflow.py``.

This module runs inside Nuke's Python interpreter (stdlib only — no third-party
packages available). ``nuke`` is already in scope when exec'd from the gizmo.
Qt (PySide2 or PySide6) is bundled with Nuke and available here.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

# run_button.py is exec'd (not imported) by the gizmo bootstrap, so __file__'s
# directory is not added to sys.path automatically. Insert it so that
# output_protocol (a sibling in the companion bundle) can be imported.
_companion_dir = os.path.dirname(os.path.abspath(__file__))
if _companion_dir not in sys.path:
    sys.path.insert(0, _companion_dir)

try:
    from output_protocol import OUTPUT_SENTINEL_BEGIN
    from output_protocol import extract_payload as _extract_runner_output

    _SENTINEL = OUTPUT_SENTINEL_BEGIN
except ImportError:
    # Fallback for older companion bundles that pre-date output_protocol.py.
    def _extract_runner_output(stdout_text: str) -> dict:  # type: ignore[misc]
        return json.loads(stdout_text.strip())

    _SENTINEL = ""


def _venv_root() -> str:
    """Return the per-machine base dir under which gizmo venvs/configs live.

    Honors XDG_DATA_HOME so sites with roaming home directories can relocate the
    venv root onto machine-local storage; falls back to ~/.local/share.
    """
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(data_home, "griptape_nodes", "venvs")


def _gizmo_local_dir(companion: str, workflow_stem: str) -> str:
    """Return the per-machine base dir for this gizmo's venv and config.

    The gizmo (and its pyproject.toml) live on a shared drive, but each artist's
    venv/config must be created locally — a venv built for one artist's machine
    crashes on another's. Deriving a per-machine path keyed on the shared
    companion location keeps distinct gizmos separate and the same gizmo stable
    across sessions on a given machine. Returns an absolute forward-slashed path.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", workflow_stem.lower()).strip("-") or "gizmo"
    # normcase(realpath(...)) collapses case- and symlink-variant companion paths
    # (e.g. C:/ vs c:/, relative vs absolute) so one gizmo keeps one venv.
    normalized = os.path.normcase(os.path.realpath(companion))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    return os.path.join(_venv_root(), f"{slug}-{digest}").replace("\\", "/")


def _build_child_env(local_dir: str, base_env: dict) -> dict:
    """Return a subprocess env pointing config and the uv venv at the local dir.

    XDG_CONFIG_HOME keeps engine config writes (e.g. projects_to_register) out of
    the user's global ~/.config, UV_PROJECT_ENVIRONMENT redirects uv's venv away
    from <companion>/.venv (which would be shared-drive) to a per-machine
    location, and UV_FROZEN stops uv from writing uv.lock back to the (possibly
    read-only) shared companion dir. local_dir must already be an absolute
    forward-slashed path.
    """
    return {
        **base_env,
        "XDG_CONFIG_HOME": local_dir + "/.gtn_config",
        "UV_PROJECT_ENVIRONMENT": local_dir + "/.venv",
        "UV_FROZEN": "1",
    }


# Qt is bundled with Nuke. Try PySide6 first (Nuke 16+), fall back to PySide2 (Nuke 13–15).
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QDialog,
        QHBoxLayout,
        QLabel,
        QProgressBar,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
    )

    _QT_AVAILABLE = True
except ImportError:
    try:
        from PySide2.QtCore import Qt
        from PySide2.QtGui import QFont
        from PySide2.QtWidgets import (
            QDialog,
            QHBoxLayout,
            QLabel,
            QProgressBar,
            QPushButton,
            QTextEdit,
            QVBoxLayout,
        )

        _QT_AVAILABLE = True
    except ImportError:
        _QT_AVAILABLE = False


# ---------------------------------------------------------------------------
# Progress dialog
# ---------------------------------------------------------------------------

if _QT_AVAILABLE:

    class _WorkflowProgressDialog(QDialog):
        """Non-modal dialog that streams workflow log output in real-time."""

        def __init__(self, title="Running Workflow", parent=None):
            super().__init__(parent)
            self.setWindowTitle(title)
            self.setMinimumSize(620, 420)
            self.setModal(False)
            self.setAttribute(Qt.WA_DeleteOnClose)

            self._cancel_callback = None
            self._closed = False

            layout = QVBoxLayout(self)

            self._status_label = QLabel("Initializing...")
            layout.addWidget(self._status_label)

            self._progress_bar = QProgressBar()
            self._progress_bar.setRange(0, 0)  # indeterminate spinner
            layout.addWidget(self._progress_bar)

            self._log_text = QTextEdit()
            self._log_text.setReadOnly(True)
            mono = QFont("Courier")
            mono.setStyleHint(QFont.Monospace)
            self._log_text.setFont(mono)
            self._log_text.setLineWrapMode(QTextEdit.NoWrap)
            layout.addWidget(self._log_text)

            btn_layout = QHBoxLayout()
            self._cancel_btn = QPushButton("Cancel")
            self._cancel_btn.clicked.connect(self._on_cancel)
            btn_layout.addStretch()
            btn_layout.addWidget(self._cancel_btn)
            layout.addLayout(btn_layout)

        def append_log(self, text):
            if self._closed:
                return
            self._log_text.append(text.rstrip("\n"))
            sb = self._log_text.verticalScrollBar()
            sb.setValue(sb.maximum())

        def set_status(self, text):
            if not self._closed:
                self._status_label.setText(text)

        def set_finished(self, success):
            if self._closed:
                return
            self._progress_bar.setRange(0, 1)
            self._progress_bar.setValue(1)
            self._cancel_btn.setText("Close")
            if success:
                self.set_status("Workflow completed successfully.")
            else:
                self.set_status("Workflow failed. See logs above.")

        def set_cancel_callback(self, callback):
            self._cancel_callback = callback

        def closeEvent(self, event):
            self._closed = True
            super().closeEvent(event)

        def _on_cancel(self):
            if self._progress_bar.maximum() != 0:
                # Already finished — just close
                self.close()
            elif self._cancel_callback:
                self._cancel_callback()


# ---------------------------------------------------------------------------
# Node tile-color helpers
# ---------------------------------------------------------------------------

# Tile color values:
#   0xff9900ff = Griptape orange (default)
#   0x3399ffff = blue (running)
#   0xff0000ff = red (error)
_DEFAULT_TILE_COLOR = 0xFF9900FF
_RUNNING_TILE_COLOR = 0x3399FFFF
_ERROR_TILE_COLOR = 0xFF0000FF


def _set_node_error(n, message: str) -> None:
    """Mark the gizmo tile red and show a short error label."""
    n["tile_color"].setValue(_ERROR_TILE_COLOR)
    n["label"].setValue("[ERROR]\n" + message[:120])
    nuke.error(message)  # noqa: F821


def _clear_node_error(n) -> None:
    """Restore the gizmo to its default (non-error) appearance."""
    n["tile_color"].setValue(_DEFAULT_TILE_COLOR)
    n["label"].setValue("")


def _set_node_running(n, is_running: bool) -> None:
    """Toggle the gizmo's visual running state and guard knob."""
    if is_running:
        n["tile_color"].setValue(_RUNNING_TILE_COLOR)
        n["label"].setValue("[RUNNING]")
    else:
        n["tile_color"].setValue(_DEFAULT_TILE_COLOR)
        n["label"].setValue("")
    if n.knob("_gt_running"):
        n["_gt_running"].setValue("1" if is_running else "0")


# ---------------------------------------------------------------------------
# uv binary helpers
# ---------------------------------------------------------------------------

_GRIPTAPE_UV_INSTALL_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "griptape_nodes", "bin")


def _uv_fallback_paths():
    """Return candidate paths for the uv binary, in priority order."""
    _is_win = platform.system() == "Windows"
    _ext = ".exe" if _is_win else ""
    return [
        os.path.join(_GRIPTAPE_UV_INSTALL_DIR, "uv" + _ext),
        os.path.expanduser("~/.local/bin/uv" + _ext),
        os.path.expanduser("~/.cargo/bin/uv" + _ext),
    ]


# ---------------------------------------------------------------------------
# Entry point — exec'd from the gizmo's PyScript_Knob
# ---------------------------------------------------------------------------

# _config is injected by the gizmo bootstrap before this file is exec'd.
_config: dict = globals().get("_config", {})

_workflow_filename: str = _config.get("workflow_filename", "")
_start_node_name: str = _config.get("start_node_name", "")
_param_names: list = _config.get("param_names", [])
_media_input_names: list = _config.get("media_input_names", [])
_frame_range_input_names: list = _config.get("frame_range_input_names", [])
_media_output_names: list = _config.get("media_output_names", [])
_media_input_index_map: dict = _config.get("media_input_index_map", {})
_media_output_read_map: dict = _config.get("media_output_read_map", {})
_output_knob_map: dict = _config.get("output_knob_map", {})
_input_node_prefix: str = _config.get("input_node_prefix", "Input")
_temp_file_prefix: str = _config.get("temp_file_prefix", "gt_input")

node = nuke.thisNode()  # noqa: F821  # 'nuke' is in scope when exec'd from the gizmo

# -- Resolve companion directory --

companion = node["_companion_dir"].value()
if not companion or not os.path.isdir(companion):
    _workflow_name = _config.get("workflow_name", "")
    if _workflow_name:
        for _d in nuke.pluginPath():  # noqa: F821
            _c = os.path.join(_d, _workflow_name)
            if os.path.isdir(_c) and os.path.isfile(os.path.join(_c, "run_button.py")):
                companion = _c
                break

if not companion or not os.path.isdir(companion):
    raise RuntimeError(
        f"Griptape: companion directory not found: {companion!r}. "
        "Re-publish the gizmo or ensure the griptape folder is on Nuke's plugin path."
    )

# Normalize to forward slashes so backslashes don't get mangled by Nuke's
# TCL string encoding when the .nk file is saved and reloaded.
companion = companion.replace("\\", "/")
node["_companion_dir"].setValue(companion)

# -- Resolve the per-machine local dir (venv + config) --
# The companion (and its pyproject.toml) may live on a shared drive; the venv
# and engine config must be created on THIS machine, not shared, or a venv built
# for one artist crashes on another's. Keyed on the normalized companion path so
# it is stable across sessions and unique per gizmo.
# workflow_name is already a stem (the publisher passes workflow_file_path.stem);
# only the workflow_filename fallback carries an extension to strip.
_workflow_stem = _config.get("workflow_name", "") or os.path.splitext(_workflow_filename)[0]
_local_dir = _gizmo_local_dir(companion, _workflow_stem)
os.makedirs(_local_dir, exist_ok=True)

# Build the child-process environment once.  XDG_CONFIG_HOME keeps the engine's
# user config writes (e.g. the projects_to_register list) out of the user's
# global ~/.config, and UV_PROJECT_ENVIRONMENT redirects uv's venv off the
# (possibly shared) companion dir onto this machine's local dir.
_child_env = _build_child_env(_local_dir, os.environ)

# -- Resolve workflow file from version subdir --

_selected_version = _config.get("version")
if _selected_version:
    workflow_file = companion + "/" + _selected_version + "/" + _workflow_filename
else:
    workflow_file = companion + "/" + _workflow_filename

runner = companion + "/run_workflow.py"

# Resolve output working directory.  The Nuke script directory is the preferred
# base so outputs live next to the .nk file.  For unsaved scripts we fall back
# to the companion directory.
_nk_script_dir = nuke.script_directory()  # noqa: F821

if _nk_script_dir:
    _nk_script_dir = _nk_script_dir.replace("\\", "/")

output_dir = node["output_dir"].value()
if output_dir:
    output_dir = output_dir.replace("\\", "/")

# -- Re-entrancy guard --

if node.knob("_gt_running") and node["_gt_running"].value() == "1":
    nuke.message("A workflow is already running on this node. Please wait for it to finish.")  # noqa: F821
else:
    # -- Collect input values from knobs --

    inputs: dict = {}
    for _k in _param_names:
        if node.knob(_k):
            inputs[_k] = node[_k].value()
            print(f"[Griptape] knob '{_k}' -> type={type(inputs[_k]).__name__!r} value={inputs[_k]!r}")
        else:
            print(f"[Griptape] knob '{_k}' -> NOT FOUND on node")

    # -- Render media inputs from upstream Nuke connections to temp files --

    for _mk in _media_input_names:
        _input_idx = _media_input_index_map[_mk]
        print(f"[Griptape] media input '{_mk}' -> checking Nuke input index {_input_idx}")
        if node.input(_input_idx) is not None:
            _is_frame_range = _mk in _frame_range_input_names
            _ext = "mov" if _is_frame_range else "jpg"
            _file_type = "mov" if _is_frame_range else "jpg"
            if _is_frame_range:
                _upstream_range = node.input(_input_idx).frameRange()  # noqa: F821
                _first = _upstream_range.first()
                _last = _upstream_range.last()
            else:
                _first = _last = int(nuke.frame())  # noqa: F821
            _tmp = os.path.join(
                tempfile.gettempdir(),
                f"{_temp_file_prefix}_{node.name()}_{_mk}.{_ext}",
            ).replace(
                "\\", "/"
            )  # Nuke/TCL treats backslashes as escape chars; forward slashes are safe on all platforms
            print(f"[Griptape] media input '{_mk}' -> rendering frames {_first}-{_last} to temp file: {_tmp!r}")
            node.begin()
            try:
                _in = nuke.toNode(f"{_input_node_prefix}{_input_idx + 1}")  # noqa: F821
                _w = nuke.nodes.Write(name="_GT_TMP_WRITE")  # noqa: F821
                _w["file"].setValue(_tmp)
                _w["file_type"].setValue(_file_type)
                _w.setInput(0, _in)
                nuke.execute(_w, _first, _last)  # noqa: F821
                nuke.delete(_w)  # noqa: F821
                print(f"[Griptape] media input '{_mk}' -> temp file written: {_tmp!r}")
            finally:
                node.end()
            inputs[_mk] = _tmp
        else:
            print(f"[Griptape] media input '{_mk}' -> no upstream Nuke connection on input {_input_idx}, skipping")

    # -- Locate uv, installing it if absent --

    print(f"[Griptape] final inputs dict before serialization: {inputs!r}")
    flow_input = json.dumps({_start_node_name: inputs})
    print(f"[Griptape] flow_input JSON: {flow_input!r}")

    uv = shutil.which("uv")
    if not uv:
        for _p in _uv_fallback_paths():
            if os.path.isfile(_p):
                uv = _p
                break

    _pre_dialog_logs: list = []

    if not uv:
        _install_env = os.environ.copy()
        _install_env["UV_UNMANAGED_INSTALL"] = _GRIPTAPE_UV_INSTALL_DIR
        msg = "Installing UV..."
        _pre_dialog_logs.append(msg)

        if platform.system() == "Windows":
            _install = subprocess.run(
                [
                    "powershell",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    "irm https://astral.sh/uv/install.ps1 | iex",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                env=_install_env,
            )
        else:
            _install = subprocess.run(
                ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
                capture_output=True,
                text=True,
                timeout=120,
                env=_install_env,
            )

        if _install.returncode != 0:
            msg = (
                "Failed to install uv automatically.\n"
                "Install it manually: https://docs.astral.sh/uv/getting-started/installation/\n"
                "Then restart Nuke."
            )
            nuke.message(msg)  # noqa: F821
            _set_node_error(node, msg)
        else:
            for _p in _uv_fallback_paths():
                if os.path.isfile(_p):
                    uv = _p
                    break

    if not os.path.isdir(os.path.join(_local_dir, ".venv")):
        _pre_dialog_logs.append(
            "Building your gizmo python environment...\n"
            "This will take a few minutes the first gizmo run, but will be faster on subsequent gizmo runs."
        )

    # -- Run the workflow --

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
        ]

        # Pass the Nuke script directory so the runner resolves project
        # directory macros (like {outputs}) relative to the .nk file.
        if _nk_script_dir:
            cmd.extend(["--nk-script-dir", _nk_script_dir])

        # Pass user-specified output dir override if set in the knob.
        if output_dir:
            cmd.extend(["--output-dir", output_dir])

        if _QT_AVAILABLE:
            # ------------------------------------------------------------------
            # Async path: non-modal progress dialog + background thread
            # ------------------------------------------------------------------

            _dialog = _WorkflowProgressDialog(title=f"Griptape: {_workflow_filename}")
            _dialog.show()

            for _pre_log in _pre_dialog_logs:
                _dialog.append_log(_pre_log)

            _process_ref = [None]  # mutable container so cancel callback can reach it
            _log_lock = threading.Lock()
            _pending_log_lines: list = []
            _all_stderr_lines: list = []

            def _cancel_process():
                p = _process_ref[0]
                if p and p.poll() is None:
                    p.terminate()

            _dialog.set_cancel_callback(_cancel_process)
            _set_node_running(node, True)

            def _flush_pending_log():
                """Append queued log lines to the dialog (runs on the main thread)."""
                with _log_lock:
                    if not _pending_log_lines:
                        return
                    batch = "".join(_pending_log_lines)
                    _pending_log_lines.clear()
                _all_stderr_lines.append(batch)
                _dialog.append_log(batch)

            def _on_result(success, stdout_text, _stderr_text):
                """Handle completion on the main thread."""
                try:
                    _ = node.name()  # raises ValueError if node was deleted
                except ValueError:
                    return

                _set_node_running(node, False)

                if success:
                    try:
                        output = _extract_runner_output(stdout_text)
                        for _k, _v in output.items():
                            _knob = _output_knob_map.get(_k, _k)
                            if node.knob(_knob):
                                node[_knob].setValue(str(_v))
                        for _mk in _media_output_names:
                            _mv = output.get(_mk, "")
                            if _mv and os.path.isfile(str(_mv)):
                                _read_name = _media_output_read_map.get(_mk)
                                if _read_name:
                                    try:
                                        node.begin()
                                        _r = nuke.toNode(_read_name)  # noqa: F821
                                        if _r:
                                            # The Read node's file knob is expression-linked
                                            # to the top-level output knob (set above via
                                            # _output_knob_map), so we only need to trigger
                                            # a reload — not overwrite the expression with
                                            # a literal path.
                                            try:
                                                _r["reload"].execute()
                                            except Exception:
                                                pass
                                    finally:
                                        node.end()
                        nuke.updateUI()  # noqa: F821
                        _clear_node_error(node)
                        _dialog.set_finished(True)
                    except Exception as _e:
                        error_message = (
                            "Error parsing output: "
                            + str(_e)
                            + "\nstdout head: "
                            + stdout_text[:300]
                            + "\nstdout tail: "
                            + stdout_text[-300:]
                        )
                        _set_node_error(node, error_message)
                        _dialog.append_log("\n--- ERROR ---\n" + error_message)
                        _dialog.set_finished(False)
                else:
                    _set_node_error(node, "Workflow failed.\n" + (_stderr_text or "No log output available."))
                    _dialog.set_finished(False)

            def _worker():
                """Background thread: run the subprocess and stream stderr to the dialog."""
                _UPDATE_INTERVAL = 0.2  # seconds between UI refreshes

                p = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    cwd=companion,
                    env=_child_env,
                )
                _process_ref[0] = p

                nuke.executeInMainThread(lambda: _dialog.set_status("Running workflow..."))  # noqa: F821

                stdout_lines: list = []

                def _read_stdout():
                    for line in iter(p.stdout.readline, ""):
                        stdout_lines.append(line)
                        if _SENTINEL and _SENTINEL in line:
                            continue
                        with _log_lock:
                            _pending_log_lines.append(line)

                def _read_stderr():
                    for line in iter(p.stderr.readline, ""):
                        with _log_lock:
                            _pending_log_lines.append(line)

                stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
                stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
                stdout_thread.start()
                stderr_thread.start()

                last_update = 0.0
                while p.poll() is None:
                    now = time.time()
                    if now - last_update >= _UPDATE_INTERVAL:
                        nuke.executeInMainThread(_flush_pending_log)  # noqa: F821
                        last_update = now
                    time.sleep(0.05)

                stdout_thread.join(timeout=5)
                stderr_thread.join(timeout=5)

                nuke.executeInMainThread(_flush_pending_log)  # noqa: F821

                nuke.executeInMainThread(  # noqa: F821
                    _on_result,
                    args=(p.returncode == 0, "".join(stdout_lines), "".join(_all_stderr_lines)),
                )

            threading.Thread(target=_worker, daemon=True).start()

        else:
            # ------------------------------------------------------------------
            # Fallback: blocking path when Qt is not available
            # ------------------------------------------------------------------
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=companion, timeout=600, env=_child_env)
            if result.returncode == 0:
                try:
                    output = _extract_runner_output(result.stdout)
                    for _k, _v in output.items():
                        _knob = _output_knob_map.get(_k, _k)
                        if node.knob(_knob):
                            node[_knob].setValue(str(_v))
                    for _mk in _media_output_names:
                        _mv = output.get(_mk, "")
                        if _mv and os.path.isfile(str(_mv)):
                            _read_name = _media_output_read_map.get(_mk)
                            if _read_name:
                                try:
                                    node.begin()
                                    _r = nuke.toNode(_read_name)  # noqa: F821
                                    if _r:
                                        # The Read node's file knob is expression-linked
                                        # to the top-level output knob (set above via
                                        # _output_knob_map), so we only need to trigger
                                        # a reload — not overwrite the expression with
                                        # a literal path.
                                        try:
                                            _r["reload"].execute()
                                        except Exception:
                                            pass
                                finally:
                                    node.end()
                    nuke.updateUI()  # noqa: F821
                    _clear_node_error(node)
                    nuke.message("Workflow completed!")  # noqa: F821
                except Exception as _e:
                    error_message = (
                        "Error parsing output: "
                        + str(_e)
                        + "\nstdout head: "
                        + result.stdout[:300]
                        + "\nstdout tail: "
                        + result.stdout[-300:]
                    )
                    nuke.message(error_message)  # noqa: F821
                    _set_node_error(node, error_message)
            else:
                full_error = "Workflow failed. Logs below:\n" + result.stderr
                nuke.message("Workflow failed:\n" + result.stderr[-2000:])  # noqa: F821
                _set_node_error(node, full_error)
