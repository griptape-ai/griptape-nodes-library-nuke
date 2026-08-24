"""Sentinel-framed output protocol shared between the gizmo runner and the run_button.

Both files are stdlib-only so they can run inside Nuke's bundled interpreter.
"""

from __future__ import annotations

import json
import sys

OUTPUT_SENTINEL_BEGIN = "<<<GTN_OUTPUT_BEGIN>>>"
OUTPUT_SENTINEL_END = "<<<GTN_OUTPUT_END>>>"


def emit_payload(payload: dict) -> None:
    """Write the sentinel-framed JSON payload to stdout, echoing any "error" text to stderr.

    run_button.py discards stdout entirely when the runner exits non-zero, so an error
    carried only in the payload would never reach the artist. It shows stderr instead, and
    filters the sentinel line out of the log, so the echo is seen exactly once.
    """
    sys.stdout.write(OUTPUT_SENTINEL_BEGIN + json.dumps(payload) + OUTPUT_SENTINEL_END + "\n")
    sys.stdout.flush()

    error = payload.get("error")
    if error:
        sys.stderr.write(str(error) + "\n")
        sys.stderr.flush()


def extract_payload(stdout_text: str) -> dict:
    """Extract the runner's sentinel-framed JSON payload from captured stdout.

    Uses rfind so that if multiple payloads appear (e.g. an early error followed
    by a final success — which shouldn't happen but is defensive), the last one wins.
    Falls back to whole-buffer JSON for backwards compatibility with older companion
    bundles that pre-date this protocol.
    """
    begin = stdout_text.rfind(OUTPUT_SENTINEL_BEGIN)
    end = stdout_text.rfind(OUTPUT_SENTINEL_END)
    if begin != -1 and end != -1 and end > begin:
        payload = stdout_text[begin + len(OUTPUT_SENTINEL_BEGIN) : end]
        return json.loads(payload)
    return json.loads(stdout_text.strip())
