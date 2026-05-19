from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile

from script_parser.annotation import ExposedKnob, GriptapeAnnotation
from script_parser.knob_filter import filter_nodes, get_filter

SCHEMA_VERSION = "griptape-nuke-annotations/1.0"


def compute_script_hash(script_path: str) -> str:
    h = hashlib.sha256()
    with open(script_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _atomic_write_json(path: str, data: dict) -> None:
    dir_ = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def write_sidecar(
    sidecar_path: str,
    script_path: str,
    annotations: list[GriptapeAnnotation],
    expose_knobs: list[ExposedKnob] | None = None,
) -> None:
    script_hash = compute_script_hash(script_path)
    entries: list[dict[str, object]] = []

    # A node with an I/O annotation (gt_role) is represented as an I/O entry.
    # Expose-only knobs on such nodes are intentionally excluded — a node is
    # either an I/O port or an expose-knobs source, not both.
    annotation_nodes = {ann.node_name for ann in annotations}

    for ann in annotations:
        entry: dict[str, object] = {
            "node": ann.node_name,
            "gt_role": ann.role,
            "gt_name": ann.gt_name,
            "gt_type": ann.gt_type,
        }
        if ann.gt_label is not None:
            entry["gt_label"] = ann.gt_label
        entries.append(entry)

    if expose_knobs:
        grouped: dict[str, list[ExposedKnob]] = {}
        for ek in expose_knobs:
            if ek.source_node not in annotation_nodes:
                grouped.setdefault(ek.source_node, []).append(ek)
        for node_name, knobs in grouped.items():
            expose_dicts: list[dict[str, str]] = []
            for ek in knobs:
                d: dict[str, str] = {"knob": ek.knob_ref}
                if ek.knob_type is not None:
                    d["type"] = ek.knob_type
                expose_dicts.append(d)
            entries.append({"node": node_name, "gt_expose": expose_dicts})

    # Preserve any existing knob_schema section so write_sidecar does not clobber it.
    existing_knob_schema: dict | None = None
    if os.path.exists(sidecar_path):
        try:
            with open(sidecar_path, encoding="utf-8") as f:
                existing = json.load(f)
            existing_knob_schema = existing.get("knob_schema")
        except (json.JSONDecodeError, OSError):
            pass

    data: dict[str, object] = {
        "schema": SCHEMA_VERSION,
        "script": os.path.basename(script_path),
        "script_hash": script_hash,
        "annotations": entries,
    }
    if existing_knob_schema is not None:
        data["knob_schema"] = existing_knob_schema

    _atomic_write_json(sidecar_path, data)


def read_sidecar(
    sidecar_path: str,
    script_path: str,
) -> tuple[list[GriptapeAnnotation], list[ExposedKnob], bool]:
    """Return (annotations, expose_knobs, is_stale).

    is_stale is True when the .nk file hash no longer matches the sidecar.
    Expose-only entries (no gt_role) are returned as ExposedKnob objects.

    Raises FileNotFoundError if the sidecar does not exist and ValueError if
    the sidecar contains malformed JSON.
    """
    try:
        with open(sidecar_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed sidecar JSON: {sidecar_path}") from exc

    stored_hash = data.get("script_hash", "")
    current_hash = compute_script_hash(script_path)
    is_stale = stored_hash != current_hash

    annotations: list[GriptapeAnnotation] = []
    expose_knobs: list[ExposedKnob] = []

    for entry in data.get("annotations", []):
        if entry.get("gt_role"):
            annotations.append(
                GriptapeAnnotation(
                    node_name=entry["node"],
                    role=entry.get("gt_role", ""),
                    gt_name=entry.get("gt_name", ""),
                    gt_type=entry.get("gt_type", ""),
                    gt_label=entry.get("gt_label"),
                )
            )
        else:
            for item in entry.get("gt_expose", []):
                ref = item.get("knob", "")
                if "." not in ref:
                    continue
                target_node, _, target_knob = ref.partition(".")
                if not target_node or not target_knob:
                    continue
                expose_knobs.append(
                    ExposedKnob(
                        source_node=entry["node"],
                        knob_ref=ref,
                        target_node=target_node,
                        target_knob=target_knob,
                        param_name=f"{target_node}_{target_knob}",
                        knob_type=item.get("type") or None,
                    )
                )

    return annotations, expose_knobs, is_stale


def write_knob_schema(
    sidecar_path: str,
    nuke_version: str,
    script_hash: str,
    nodes: dict[str, dict],
) -> None:
    """Merge or create the knob_schema section in the sidecar file.

    Reads the existing sidecar if present; replaces the knob_schema key; writes back
    atomically. Existing annotations are preserved.
    """
    if os.path.exists(sidecar_path):
        try:
            with open(sidecar_path, encoding="utf-8") as f:
                data: dict = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {
                "schema": SCHEMA_VERSION,
                "script": os.path.basename(sidecar_path).removesuffix(".gt.json") + ".nk",
                "script_hash": script_hash,
                "annotations": [],
            }
    else:
        data = {
            "schema": SCHEMA_VERSION,
            "script": os.path.basename(sidecar_path).removesuffix(".gt.json") + ".nk",
            "script_hash": script_hash,
            "annotations": [],
        }

    knob_filter = get_filter(nuke_version)
    data["knob_schema"] = {
        "nuke_version": nuke_version,
        "script_hash": script_hash,
        "nodes": filter_nodes(nodes, knob_filter),
    }

    _atomic_write_json(sidecar_path, data)


def read_knob_schema(sidecar_path: str) -> dict[str, dict] | None:
    """Return the nodes dict from knob_schema, or None if absent or sidecar missing."""
    try:
        with open(sidecar_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    section = data.get("knob_schema")
    if not isinstance(section, dict):
        return None
    return section.get("nodes")
