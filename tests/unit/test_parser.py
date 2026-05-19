from __future__ import annotations

import os

from script_parser.parser import parse_script

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(filename: str) -> str:
    with open(os.path.join(FIXTURES, filename), encoding="utf-8") as f:
        return f.read()


def test_parser_extracts_node_class_and_name() -> None:
    nodes = parse_script(_load("annotated_read_write.nk"))
    names = {n.name: n.node_class for n in nodes}
    assert names["GradeInput"] == "Read"
    assert names["GradeOutput"] == "Write"


def test_parser_extracts_gt_knob_values() -> None:
    nodes = parse_script(_load("annotated_read_write.nk"))
    read = next(n for n in nodes if n.name == "GradeInput")
    assert read.knobs["gt_role"] == "input"
    assert read.knobs["gt_name"] == "source_image"
    assert read.knobs["gt_type"] == "ImageArtifact"
    assert read.knobs["gt_label"] == "Source Image"


def test_parser_handles_multiple_nodes() -> None:
    nodes = parse_script(_load("annotated_read_write.nk"))
    assert len(nodes) == 2


def test_parser_skips_root_node() -> None:
    nodes = parse_script(_load("annotated_read_write.nk"))
    assert all(n.node_class != "Root" for n in nodes)


def test_parser_returns_nodes_with_no_gt_knobs() -> None:
    nodes = parse_script(_load("no_annotations.nk"))
    assert len(nodes) == 1
    assert nodes[0].node_class == "Blur"
    assert nodes[0].name == "Blur1"
    assert not any(k.startswith("gt_") for k in nodes[0].knobs)


def test_parser_extracts_expose_knob() -> None:
    nodes = parse_script(_load("exposed_knob.nk"))
    grade = next(n for n in nodes if n.name == "Grade1")
    assert grade.knobs.get("gt_expose_white") == "Grade1.white"
