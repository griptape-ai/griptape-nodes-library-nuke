"""Nuke headless bake runner.

Invoked by DirectSubprocessProvider as:
    nuke -t baker.py --manifest /path/to/manifest.json --output-manifest /path/to/out.json

Opens the .nk script, applies all inputs and knob overrides, then saves a copy to
manifest["bake_output_path"] using nuke.scriptSaveAs. No frames are rendered.

Stdlib + nuke module only — no third-party imports.
"""

from __future__ import annotations

import argparse
import json
import sys

import nuke


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-manifest", required=True)
    args, _ = parser.parse_known_args()

    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)

    bake_path = manifest.get("bake_output_path", "").strip()
    if not bake_path:
        print("ERROR: bake_output_path is empty in manifest", file=sys.stderr)
        sys.exit(1)

    script_path = manifest["script"]
    print(f"loading script: {script_path}", file=sys.stderr)
    nuke.scriptOpen(script_path)

    try:
        nuke.root()["proxy"].setValue(False)
    except Exception:
        pass

    for gt_name, spec in manifest.get("inputs", {}).items():
        node = nuke.toNode(spec["node"])
        if node is None:
            print(f"WARNING: input node {spec['node']!r} not found", file=sys.stderr)
            continue
        path = spec["path"].replace("\\", "/")
        node["file"].setValue(path)
        print(f"input {gt_name!r}: {spec['node']}.file = {path}", file=sys.stderr)

    for override in manifest.get("knob_overrides", []):
        node = nuke.toNode(override["node"])
        if node is None:
            print(f"WARNING: override node {override['node']!r} not found", file=sys.stderr)
            continue
        node[override["knob"]].setValue(override["value"])
        print(f"override {override['node']}.{override['knob']} = {override['value']}", file=sys.stderr)

    bake_path_fwd = bake_path.replace("\\", "/")
    print(f"saving baked copy: {bake_path_fwd}", file=sys.stderr)
    nuke.scriptSaveAs(bake_path_fwd, overwrite=1)

    with open(args.output_manifest, "w", encoding="utf-8") as f:
        json.dump({"outputs": {"baked_script": bake_path_fwd}}, f)
    sys.exit(0)


if __name__ == "__main__":
    main()
