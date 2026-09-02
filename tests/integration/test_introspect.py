from __future__ import annotations

import json
import os
import subprocess

import pytest

nuke_exe = os.environ.get("NUKE_EXECUTABLE")
pytestmark = pytest.mark.skipif(not nuke_exe, reason="NUKE_EXECUTABLE not set")

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "unit", "fixtures")
SCRIPT_PATH = os.path.join(FIXTURES, "annotated_read_write.nk")
INTROSPECT_SCRIPT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "nuke_runner", "introspect.py")
)


def _run_introspect() -> dict:
    assert nuke_exe is not None
    result = subprocess.run(  # noqa: S603
        [nuke_exe, "-t", INTROSPECT_SCRIPT, "--script", SCRIPT_PATH],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"introspect.py exited {result.returncode}:\n{result.stderr}"
    # Take last line - lines above are Nuke copyright notice etc.
    return json.loads(result.stdout.splitlines()[-1])


def test_introspect_returns_valid_json_for_annotated_script() -> None:
    schema = _run_introspect()
    assert isinstance(schema, dict)
    assert len(schema) >= 1


def test_introspect_schema_includes_knob_label_type_value() -> None:
    schema = _run_introspect()
    for node_data in schema.values():
        assert "class" in node_data
        assert "knobs" in node_data
        for knob_data in node_data["knobs"].values():
            assert "label" in knob_data
            assert "type" in knob_data
            assert "value" in knob_data
        return
    pytest.fail("schema was empty")
