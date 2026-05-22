"""Tests for publish_gizmo/output_protocol.py — sentinel framing and extraction."""

from __future__ import annotations

import io
import json
import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent / "publish_gizmo"))

from output_protocol import (
    OUTPUT_SENTINEL_BEGIN,
    OUTPUT_SENTINEL_END,
    emit_payload,
    extract_payload,
)


def _capture_emit(payload: dict) -> str:
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        emit_payload(payload)
    finally:
        sys.stdout = old
    return buf.getvalue()


class TestEmitPayload:
    def test_round_trip(self):
        payload = {"image_url": "/tmp/out.jpg", "image_url_1": "/tmp/out2.jpg"}
        raw = _capture_emit(payload)
        assert raw.startswith(OUTPUT_SENTINEL_BEGIN)
        assert OUTPUT_SENTINEL_END in raw
        assert extract_payload(raw) == payload

    def test_emits_newline_at_end(self):
        raw = _capture_emit({"a": "b"})
        assert raw.endswith("\n")

    def test_empty_dict(self):
        raw = _capture_emit({})
        assert extract_payload(raw) == {}


class TestExtractPayload:
    def _frame(self, payload: dict) -> str:
        return OUTPUT_SENTINEL_BEGIN + json.dumps(payload) + OUTPUT_SENTINEL_END + "\n"

    def test_clean_stdout(self):
        framed = self._frame({"k": "v"})
        assert extract_payload(framed) == {"k": "v"}

    def test_ansi_pollution_before_payload(self):
        pollution = "\x1b[1msome rich panel output\n╭─────╮\n│ foo │\n╰─────╯\n"
        framed = self._frame({"result": "ok"})
        assert extract_payload(pollution + framed) == {"result": "ok"}

    def test_pollution_after_payload(self):
        framed = self._frame({"result": "ok"})
        assert extract_payload(framed + "trailing noise\n") == {"result": "ok"}

    def test_pollution_before_and_after(self):
        framed = self._frame({"x": "1"})
        assert extract_payload("noise before\n" + framed + "noise after\n") == {"x": "1"}

    def test_multiple_framed_payloads_returns_last(self):
        first = self._frame({"error": "early exit"})
        second = self._frame({"image_url": "/final.jpg"})
        assert extract_payload(first + second) == {"image_url": "/final.jpg"}

    def test_backwards_compat_no_sentinels_valid_json(self):
        plain = json.dumps({"legacy": "value"}) + "\n"
        assert extract_payload(plain) == {"legacy": "value"}

    def test_malformed_payload_raises(self):
        malformed = OUTPUT_SENTINEL_BEGIN + "not json at all" + OUTPUT_SENTINEL_END
        with pytest.raises(json.JSONDecodeError):
            extract_payload(malformed)

    def test_backwards_compat_no_sentinels_malformed_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_payload("\x1b[1mrich panel output\n")
