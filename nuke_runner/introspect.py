"""Knob schema introspector — runs inside nuke -t.

Loads the given .nk script and dumps the full knob schema for every node as JSON.
Only stdlib and the nuke module are used; no third-party imports.
"""

from __future__ import annotations

import argparse
import json
import sys

import nuke


def _to_json(v: object) -> object:
    """Coerce a knob value to a JSON-serializable type."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [_to_json(i) for i in v]
    return str(v)


def _safe(fn, *args):
    """Call fn(*args), returning None on any exception."""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump full knob schema for all nodes in a .nk script")
    parser.add_argument("--script", required=True, help="Path to the .nk script")
    parser.add_argument("--output", default="-", help="Output file path (default: stdout)")
    args = parser.parse_args()

    nuke.scriptOpen(args.script)

    schema: dict[str, dict] = {}
    for node in nuke.allNodes(recurseGroups=True):
        knobs: dict[str, dict] = {}
        for name, knob in node.knobs().items():
            entry: dict[str, object] = {
                "label": _safe(knob.label),
                "type": type(knob).__name__,
                "value": _to_json(_safe(knob.value)),
                "default": _to_json(_safe(knob.defaultValue)) if hasattr(knob, "defaultValue") else None,
                "is_default": _safe(knob.isDefault) if hasattr(knob, "isDefault") else None,
            }
            knobs[name] = entry
        schema[node.name()] = {"class": node.Class(), "knobs": knobs}

    payload = json.dumps(schema)
    if args.output == "-":
        print(payload)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload)

    sys.exit(0)


if __name__ == "__main__":
    main()
