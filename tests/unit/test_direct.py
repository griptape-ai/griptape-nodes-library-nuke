from __future__ import annotations

import itertools
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from execution.direct import DirectSubprocessProvider
from execution.provider import JobStatus
from nuke_runner.manifest import JobManifest


def _make_manifest(**kwargs: object) -> JobManifest:
    defaults: dict[str, object] = {"script": "/path/to/comp.nk"}
    defaults.update(kwargs)
    return JobManifest(**defaults)  # type: ignore[arg-type]


def _make_provider() -> DirectSubprocessProvider:
    return DirectSubprocessProvider(nuke_exe="/usr/bin/nuke", runner_script="/opt/runner.py")


def _mock_process(poll_return: int | None = None, communicate_stdout: str = "") -> MagicMock:
    proc = MagicMock()
    proc.poll.return_value = poll_return
    proc.communicate.return_value = (communicate_stdout, "")
    proc.returncode = poll_return if poll_return is not None else 0
    proc.stderr = iter([])
    return proc


def test_submit_spawns_nuke_with_correct_args() -> None:
    provider = _make_provider()
    with patch("execution.direct.subprocess.Popen") as mock_popen:
        mock_popen.return_value = _mock_process()
        handle = provider.submit(_make_manifest())

    args = mock_popen.call_args[0][0]
    assert args[0] == "/usr/bin/nuke"
    assert args[1] == "-t"
    assert args[2] == "/opt/runner.py"
    assert args[3] == "--manifest"
    assert args[4].endswith(".json")
    assert args[5] == "--output-manifest"
    assert args[6].endswith(".out.json")
    assert handle  # non-empty UUID string


def test_submit_writes_manifest_env_into_subprocess_env() -> None:
    provider = _make_provider()
    manifest = _make_manifest(env={"foundry_LICENSE": "4101@lic.studio.com", "OCIO": "/ocio/config"})
    with patch("execution.direct.subprocess.Popen") as mock_popen:
        mock_popen.return_value = _mock_process()
        provider.submit(manifest)

    env_kwarg = mock_popen.call_args[1]["env"]
    assert env_kwarg["foundry_LICENSE"] == "4101@lic.studio.com"
    assert env_kwarg["OCIO"] == "/ocio/config"


def test_submit_returns_unique_handles_per_call() -> None:
    provider = _make_provider()
    with patch("execution.direct.subprocess.Popen", return_value=_mock_process()):
        h1 = provider.submit(_make_manifest())
        h2 = provider.submit(_make_manifest())
    assert h1 != h2


def test_status_returns_running_while_process_active() -> None:
    provider = _make_provider()
    with patch("execution.direct.subprocess.Popen", return_value=_mock_process(poll_return=None)):
        handle = provider.submit(_make_manifest())
    assert provider.status(handle) == JobStatus.RUNNING


def test_status_returns_succeeded_on_zero_exit_code() -> None:
    provider = _make_provider()
    with patch("execution.direct.subprocess.Popen", return_value=_mock_process(poll_return=0)):
        handle = provider.submit(_make_manifest())
    assert provider.status(handle) == JobStatus.SUCCEEDED


def test_status_returns_failed_on_nonzero_exit_code() -> None:
    provider = _make_provider()
    with patch("execution.direct.subprocess.Popen", return_value=_mock_process(poll_return=1)):
        handle = provider.submit(_make_manifest())
    assert provider.status(handle) == JobStatus.FAILED


def test_cancel_kills_process_if_sigterm_not_honoured() -> None:
    proc = _mock_process()
    proc.poll.return_value = None  # never exits on its own

    provider = _make_provider()
    with patch("execution.direct.subprocess.Popen", return_value=proc):
        handle = provider.submit(_make_manifest())

    with patch("execution.direct.time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(100.0))):
        with patch("execution.direct.time.sleep"):
            provider.cancel(handle)

    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()
    proc.wait.assert_called_once()


def test_result_parses_output_paths_from_output_manifest_file(tmp_path) -> None:
    proc = _mock_process(poll_return=0)
    proc.returncode = 0

    provider = _make_provider()
    with patch("execution.direct.subprocess.Popen", return_value=proc):
        handle = provider.submit(_make_manifest())

    # Write a fake output manifest where the runner would have written it
    out_manifest_path = provider._output_manifest_paths[handle]
    with open(out_manifest_path, "w") as f:
        json.dump({"outputs": {"graded_image": "/tmp/out.png"}}, f)

    result = provider.result(handle)
    assert result.status == JobStatus.SUCCEEDED
    assert result.outputs["graded_image"] == "/tmp/out.png"
    assert result.return_code == 0


def test_init_raises_when_installation_set_without_runner_script() -> None:
    from execution.installations import NukeInstallation

    inst = NukeInstallation(display_name="Nuke16", executable_path="/opt/nuke16")
    with pytest.raises(ValueError, match="runner_script"):
        DirectSubprocessProvider(installation=inst)


def test_init_raises_when_no_installation_and_no_nuke_exe() -> None:
    with pytest.raises(ValueError, match="nuke_exe"):
        DirectSubprocessProvider()


def test_result_cleans_up_manifest_tempfiles() -> None:
    proc = _mock_process(poll_return=0)
    proc.returncode = 0

    provider = _make_provider()
    with patch("execution.direct.subprocess.Popen", return_value=proc):
        handle = provider.submit(_make_manifest())

    manifest_path = provider._manifest_paths[handle]
    out_manifest_path = provider._output_manifest_paths[handle]
    assert os.path.exists(manifest_path)

    # Create the output manifest so the cleanup assertion is non-trivial.
    with open(out_manifest_path, "w") as f:
        json.dump({"outputs": {}}, f)
    assert os.path.exists(out_manifest_path)

    provider.result(handle)
    assert not os.path.exists(manifest_path)
    assert not os.path.exists(out_manifest_path)
