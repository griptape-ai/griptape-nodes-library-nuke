"""Tests for nuke_workflow_runner.py emit_payload integration."""

from __future__ import annotations

import io
import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent / "publish_gizmo"))

from output_protocol import OUTPUT_SENTINEL_BEGIN, OUTPUT_SENTINEL_END, extract_payload


def test_emit_payload_format():
    """The framed buffer contains valid JSON between the sentinels."""
    from output_protocol import emit_payload

    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        emit_payload({"image_url": "/path/to/out.jpg"})
    finally:
        sys.stdout = old

    raw = buf.getvalue()
    assert OUTPUT_SENTINEL_BEGIN in raw
    assert OUTPUT_SENTINEL_END in raw
    inner = raw[raw.index(OUTPUT_SENTINEL_BEGIN) + len(OUTPUT_SENTINEL_BEGIN) : raw.index(OUTPUT_SENTINEL_END)]
    parsed = json.loads(inner)
    assert parsed == {"image_url": "/path/to/out.jpg"}


def test_extract_payload_round_trips_emit():
    from output_protocol import emit_payload

    payload = {"image_url": "/a.jpg", "image_url_1": "/b.jpg"}
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        emit_payload(payload)
    finally:
        sys.stdout = old

    assert extract_payload(buf.getvalue()) == payload


def test_extract_payload_with_simulated_rich_pollution():
    """Simulate the actual Agent-run stdout: ANSI art before the JSON sentinel."""
    ansi_art = "\x1b[1m\x1b[0m╭── Griptape Nodes ──╮\n│ libraries loaded   │\n╰────────────────────╯\n"
    payload = {"image_url": "/outputs/gen.jpg"}
    framed = OUTPUT_SENTINEL_BEGIN + json.dumps(payload) + OUTPUT_SENTINEL_END + "\n"
    combined = ansi_art + framed
    assert extract_payload(combined) == payload
