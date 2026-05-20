"""Nuke headless runner.

Invoked by DirectSubprocessProvider as:
    nuke -t runner.py --manifest /path/to/manifest.json --output-manifest /path/to/output.json

Stdlib + nuke module only — no third-party imports.
Logs go to stderr; the final output manifest JSON is written to --output-manifest.
"""

from __future__ import annotations

import argparse
import glob as _glob
import json
import re
import sys

import nuke  # type: ignore[import-not-found]

# Artifact types whose output is written by a Nuke execute call on a file-knob node.
_EXECUTE_TYPES = {
    "ImageArtifact",
    "ImageSequenceArtifact",
    "ImageUrlArtifact",
    "VideoArtifact",
    "VideoUrlArtifact",
    "BlobArtifact",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-manifest", required=True)
    # parse_known_args: nuke -t may inject extra positional args
    args, _ = parser.parse_known_args()

    outputs: dict[str, str | list[str]] = {}
    errors: list[str] = []

    try:
        with open(args.manifest, encoding="utf-8") as f:
            manifest = json.load(f)

        script_path = manifest["script"]
        print(f"loading script: {script_path}", file=sys.stderr)
        nuke.scriptOpen(script_path)

        # Disable proxy mode so Write nodes don't require a proxy file path.
        try:
            nuke.root()["proxy"].setValue(False)
        except Exception:
            pass

        # Apply inputs: patch file knob on annotated Read nodes
        for gt_name, spec in manifest.get("inputs", {}).items():
            node = nuke.toNode(spec["node"])
            if node is None:
                print(f"WARNING: input node {spec['node']!r} not found in script", file=sys.stderr)
                continue
            path = spec["path"].replace("\\", "/")
            node["file"].setValue(path)
            print(f"input {gt_name!r}: {spec['node']}.file = {path}", file=sys.stderr)

        # Apply knob overrides
        for override in manifest.get("knob_overrides", []):
            node = nuke.toNode(override["node"])
            if node is None:
                print(f"WARNING: override node {override['node']!r} not found in script", file=sys.stderr)
                continue
            try:
                node[override["knob"]].setValue(override["value"])
            except Exception as exc:
                print(
                    f"WARNING: knob override {override['node']}.{override['knob']} failed: {exc}",
                    file=sys.stderr,
                )
                continue
            print(f"override {override['node']}.{override['knob']} = {override['value']}", file=sys.stderr)

        # Execute outputs: set Write node paths and render
        frame_range = manifest.get("frame_range", [1001, 1001])
        first, last = frame_range[0], frame_range[1]

        for gt_name, spec in manifest.get("outputs", {}).items():
            out_path = spec["path"].replace("\\", "/")
            artifact_type = spec.get("type", "ImageArtifact")

            # Only image/video/blob types are executed via Write-node file knob.
            # 3D types require a dedicated exporter; unknown types are skipped entirely.
            if artifact_type not in _EXECUTE_TYPES:
                print(
                    f"WARNING: skipping output {gt_name!r} — artifact type {artifact_type!r} not executable via Write node",
                    file=sys.stderr,
                )
                continue
            node = nuke.toNode(spec["node"])
            if node is None:
                print(f"WARNING: output node {spec['node']!r} not found in script", file=sys.stderr)
                continue
            node["file"].setValue(out_path)
            print(f"executing {spec['node']} frames {first}-{last} → {out_path}", file=sys.stderr)
            try:
                nuke.execute(spec["node"], first, last)
                if artifact_type == "ImageSequenceArtifact":
                    glob_pattern = re.sub(r"%0?\d*d", "*", out_path)
                    frame_paths = sorted(_glob.glob(glob_pattern))
                    outputs[gt_name] = frame_paths
                else:
                    outputs[gt_name] = out_path
            except Exception as exc:
                msg = f"ERROR: execute failed for {spec['node']!r}: {exc}"
                print(msg, file=sys.stderr)
                errors.append(msg)

    except Exception as exc:
        msg = f"FATAL: {exc}"
        print(msg, file=sys.stderr)
        errors.append(msg)
    finally:
        # Always write the output manifest so the provider never reads a missing file.
        with open(args.output_manifest, "w", encoding="utf-8") as f:
            json.dump({"outputs": outputs}, f)

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
