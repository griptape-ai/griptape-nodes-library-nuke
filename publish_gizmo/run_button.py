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

import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time

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
# Entry point — exec'd from the gizmo's PyScript_Knob
# ---------------------------------------------------------------------------

# _config is injected by the gizmo bootstrap before this file is exec'd.
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
                node["_companion_dir"].setValue(companion)
                break

if not companion or not os.path.isdir(companion):
    raise RuntimeError(
        f"Griptape: companion directory not found: {companion!r}. "
        "Re-publish the gizmo or ensure the griptape folder is on Nuke's plugin path."
    )

# -- Resolve workflow file from version subdir --

_selected_version = _config.get("version")
if _selected_version:
    workflow_file = os.path.join(companion, _selected_version, _workflow_filename)
else:
    workflow_file = os.path.join(companion, _workflow_filename)

runner = os.path.join(companion, "run_workflow.py")

# Populate output_dir from the companion if the knob is empty.
output_dir = node["output_dir"].value()
if not output_dir:
    output_dir = os.path.join(companion, "outputs")
    node["output_dir"].setValue(output_dir)

# -- Re-entrancy guard --

if node.knob("_gt_running") and node["_gt_running"].value() == "1":
    nuke.message("A workflow is already running on this node. Please wait for it to finish.")  # noqa: F821
else:
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
            _set_node_error(node, msg)

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
            "--output-dir",
            output_dir,
        ]

        if _QT_AVAILABLE:
            # ------------------------------------------------------------------
            # Async path: non-modal progress dialog + background thread
            # ------------------------------------------------------------------

            _dialog = _WorkflowProgressDialog(title=f"Griptape: {_workflow_filename}")
            _dialog.show()

            _process_ref = [None]  # mutable container so cancel callback can reach it
            _log_lock = threading.Lock()
            _pending_log_lines: list = []

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
                        output = json.loads(stdout_text.strip())
                        for _k, _v in output.items():
                            if node.knob(_k):
                                node[_k].setValue(str(_v))
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
                        _clear_node_error(node)
                        _dialog.set_finished(True)
                    except Exception as _e:
                        error_message = "Error parsing output: " + str(_e) + "\n" + stdout_text[:300]
                        _set_node_error(node, error_message)
                        _dialog.append_log("\n--- ERROR ---\n" + error_message)
                        _dialog.set_finished(False)
                else:
                    _set_node_error(node, "Workflow failed. See the log dialog for details.")
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
                )
                _process_ref[0] = p

                nuke.executeInMainThread(lambda: _dialog.set_status("Running workflow..."))  # noqa: F821

                stdout_lines: list = []

                def _read_stdout():
                    for line in iter(p.stdout.readline, ""):
                        stdout_lines.append(line)

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
                    args=(p.returncode == 0, "".join(stdout_lines), ""),
                )

            threading.Thread(target=_worker, daemon=True).start()

        else:
            # ------------------------------------------------------------------
            # Fallback: blocking path when Qt is not available
            # ------------------------------------------------------------------
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=companion, timeout=600)
            if result.returncode == 0:
                try:
                    output = json.loads(result.stdout.strip())
                    for _k, _v in output.items():
                        if node.knob(_k):
                            node[_k].setValue(str(_v))
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
                    _clear_node_error(node)
                    nuke.message("Workflow completed!")  # noqa: F821
                except Exception as _e:
                    error_message = "Error parsing output: " + str(_e) + "\n" + result.stdout[:300]
                    nuke.message(error_message)  # noqa: F821
                    _set_node_error(node, error_message)
            else:
                full_error = "Workflow failed. Logs below:\n" + result.stderr
                nuke.message("Workflow failed:\n" + result.stderr[-2000:])  # noqa: F821
                _set_node_error(node, full_error)
