from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING

from execution.provider import JobResult, JobStatus
from nuke_runner.manifest import JobManifest

if TYPE_CHECKING:
    from execution.installations import NukeInstallation

_CANCEL_GRACE_SECONDS = 5

# Qt plugin paths inherited from the engine's venv (e.g. cv2 ships its own) shadow
# Nuke's bundled Qt plugins and crash the headless process on Linux.
_STRIPPED_QT_VARS = ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH")

# The engine runs in a Python 3.12 venv; `nuke -t` runs Nuke's own bundled
# interpreter (3.10/3.11 depending on the release). Leaking the engine's Python
# vars puts 3.12 site-packages -- including compiled extensions built against a
# different ABI -- ahead of Nuke's own, which crashes it rather than failing to
# import. Same leak in the opposite direction as _LEAKED_PYTHON_VARS in
# publish_gizmo/run_button.py.
#
# Deliberately narrower than that list, and duplicated rather than shared:
# run_button.py is exec'd standalone inside Nuke and can only import its own
# companion-bundle siblings, so it cannot read this constant. The differences are
# intentional -- UV_PYTHON/UV_SYSTEM_PYTHON are meaningless here (no uv involved),
# and PYTHONNOUSERSITE is omitted because user site-packages are version-keyed, so
# a 3.12 user tree won't load under Nuke's 3.10/3.11 anyway. Add to both lists when
# the var would hijack either interpreter.
_STRIPPED_PYTHON_VARS = ("PYTHONPATH", "PYTHONHOME", "PYTHONEXECUTABLE", "VIRTUAL_ENV")


class DirectSubprocessProvider:
    """Runs Nuke as a direct child process. Default provider for local dev."""

    def __init__(
        self,
        nuke_exe: str = "",
        runner_script: str = "",
        *,
        installation: NukeInstallation | None = None,
    ) -> None:
        if installation is not None and not runner_script:
            raise ValueError("runner_script must be provided when installation is set")
        if installation is None and not nuke_exe:
            raise ValueError("nuke_exe must be provided when installation is not set")
        self._nuke_exe = nuke_exe
        self._runner_script = runner_script
        self._installation = installation
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._manifest_paths: dict[str, str] = {}
        self._output_manifest_paths: dict[str, str] = {}

    def _build_cmd(self, manifest_path: str, output_manifest_path: str) -> list[str]:
        if self._installation is not None:
            from execution.installations import build_launch_command

            return build_launch_command(self._installation, self._runner_script, manifest_path, output_manifest_path)
        return [
            self._nuke_exe,
            "-t",
            self._runner_script,
            "--manifest",
            manifest_path,
            "--output-manifest",
            output_manifest_path,
        ]

    def submit(self, manifest: JobManifest) -> str:
        handle = str(uuid.uuid4())
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        tmp.write(manifest.to_json())
        tmp.close()
        self._manifest_paths[handle] = tmp.name
        out_manifest = tmp.name + ".out.json"
        self._output_manifest_paths[handle] = out_manifest
        env = os.environ.copy()
        # Strip inherited Qt plugin paths and the engine's own Python vars, which would
        # otherwise shadow what Nuke's bundled interpreter and Qt need.
        # Done before manifest overrides so callers can explicitly set these if needed.
        for _var in (*_STRIPPED_QT_VARS, *_STRIPPED_PYTHON_VARS):
            env.pop(_var, None)
        if self._installation is not None:
            env.update(self._installation.env_overrides)
        env.update(manifest.env)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        process = subprocess.Popen(
            self._build_cmd(tmp.name, out_manifest),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self._processes[handle] = process
        return handle

    def status(self, handle: str) -> JobStatus:
        code = self._processes[handle].poll()
        if code is None:
            return JobStatus.RUNNING
        return JobStatus.SUCCEEDED if code == 0 else JobStatus.FAILED

    def stream_logs(self, handle: str) -> Iterator[str]:
        # Mutually exclusive with result(): both consume stderr. Do not call result()
        # after streaming — the log field on the returned JobResult will be empty.
        process = self._processes[handle]
        assert process.stderr is not None
        for line in process.stderr:
            yield line.rstrip("\n")

    def _cleanup(self, handle: str) -> None:
        for paths in (self._manifest_paths, self._output_manifest_paths):
            p = paths.pop(handle, None)
            if p and os.path.exists(p):
                os.unlink(p)
        self._processes.pop(handle, None)

    def cancel(self, handle: str) -> None:
        process = self._processes[handle]
        process.terminate()
        deadline = time.monotonic() + _CANCEL_GRACE_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            time.sleep(0.1)
        else:
            process.kill()
            process.wait()
        self._cleanup(handle)

    def result(self, handle: str) -> JobResult:
        process = self._processes[handle]
        _, stderr_output = process.communicate()
        return_code = process.returncode
        status = JobStatus.SUCCEEDED if return_code == 0 else JobStatus.FAILED
        outputs: dict[str, str] = {}
        out_manifest_path = self._output_manifest_paths.get(handle, None)
        if out_manifest_path and os.path.exists(out_manifest_path):
            with open(out_manifest_path, encoding="utf-8") as f:
                outputs = json.load(f).get("outputs", {})
        log = [line for line in (stderr_output or "").splitlines() if line]
        self._cleanup(handle)
        return JobResult(handle=handle, status=status, return_code=return_code, outputs=outputs, log=log)
