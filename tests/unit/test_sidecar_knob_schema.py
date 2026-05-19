from __future__ import annotations

import json
import os

from script_parser.sidecar import read_knob_schema, write_knob_schema, write_sidecar

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SCRIPT_PATH = os.path.join(FIXTURES, "annotated_read_write.nk")

_NODES = {
    "Grade1": {
        "class": "Grade",
        "knobs": {
            "gain": {"label": "Gain", "type": "Double_Knob", "value": 1.2, "default": 1.0, "is_default": False},
            "gamma": {"label": "Gamma", "type": "Double_Knob", "value": 1.0, "default": 1.0, "is_default": True},
        },
    }
}


def test_write_knob_schema_creates_knob_schema_key(tmp_path) -> None:
    sidecar = str(tmp_path / "shot.gt.json")
    write_sidecar(sidecar, SCRIPT_PATH, [])
    write_knob_schema(sidecar, "16.0v4", "sha256:abc", _NODES)

    with open(sidecar, encoding="utf-8") as f:
        data = json.load(f)

    assert "knob_schema" in data
    assert data["knob_schema"]["nuke_version"] == "16.0v4"
    assert "Grade1" in data["knob_schema"]["nodes"]


def test_write_knob_schema_merges_with_existing_annotations(tmp_path) -> None:
    from script_parser.annotation import GriptapeAnnotation

    sidecar = str(tmp_path / "shot.gt.json")
    ann = GriptapeAnnotation(node_name="GradeInput", role="input", gt_name="src", gt_type="ImageArtifact")
    write_sidecar(sidecar, SCRIPT_PATH, [ann])
    write_knob_schema(sidecar, "16.0v4", "sha256:abc", _NODES)

    with open(sidecar, encoding="utf-8") as f:
        data = json.load(f)

    assert len(data["annotations"]) == 1
    assert data["annotations"][0]["node"] == "GradeInput"
    assert "knob_schema" in data


def test_read_knob_schema_returns_none_when_absent(tmp_path) -> None:
    sidecar = str(tmp_path / "shot.gt.json")
    write_sidecar(sidecar, SCRIPT_PATH, [])
    assert read_knob_schema(sidecar) is None


def test_read_knob_schema_returns_nodes_dict(tmp_path) -> None:
    sidecar = str(tmp_path / "shot.gt.json")
    write_knob_schema(sidecar, "16.0v4", "sha256:abc", _NODES)
    nodes = read_knob_schema(sidecar)
    assert nodes is not None
    assert nodes["Grade1"]["class"] == "Grade"
    assert nodes["Grade1"]["knobs"]["gain"]["value"] == 1.2


def test_read_knob_schema_returns_none_when_sidecar_missing(tmp_path) -> None:
    assert read_knob_schema(str(tmp_path / "nonexistent.gt.json")) is None


def test_write_knob_schema_filters_obsolete_knob_type(tmp_path) -> None:
    sidecar = str(tmp_path / "shot.gt.json")
    nodes_with_obsolete = {
        "Write1": {
            "class": "Write",
            "knobs": {
                "file": {"label": "", "type": "File_Knob", "value": "", "default": None, "is_default": None},
                "layer": {"label": "", "type": "Obsolete_Knob", "value": None, "default": None, "is_default": None},
            },
        }
    }
    write_knob_schema(sidecar, "16.0v4", "sha256:abc", nodes_with_obsolete)

    with open(sidecar, encoding="utf-8") as f:
        data = json.load(f)

    knobs = data["knob_schema"]["nodes"]["Write1"]["knobs"]
    assert "layer" not in knobs
    assert "file" in knobs


def test_write_knob_schema_filters_panel_dropped_knobs(tmp_path) -> None:
    sidecar = str(tmp_path / "shot.gt.json")
    nodes_with_panel_dropped = {
        "CheckerBoard1": {
            "class": "CheckerBoard2",
            "knobs": {
                "color0": {"label": "color 0", "type": "AColor_Knob", "value": 1.0, "default": 1.0, "is_default": None},
                "color0_panelDropped": {
                    "label": "panel dropped state",
                    "type": "Boolean_Knob",
                    "value": False,
                    "default": 0.0,
                    "is_default": None,
                },
            },
        }
    }
    write_knob_schema(sidecar, "16.0v4", "sha256:abc", nodes_with_panel_dropped)

    with open(sidecar, encoding="utf-8") as f:
        data = json.load(f)

    knobs = data["knob_schema"]["nodes"]["CheckerBoard1"]["knobs"]
    assert "color0_panelDropped" not in knobs
    assert "color0" in knobs


def test_write_knob_schema_overwrites_stale_schema(tmp_path) -> None:
    sidecar = str(tmp_path / "shot.gt.json")
    write_knob_schema(sidecar, "15.0v1", "sha256:old", {"OldNode": {"class": "Blur", "knobs": {}}})
    write_knob_schema(sidecar, "16.0v4", "sha256:new", _NODES)

    with open(sidecar, encoding="utf-8") as f:
        data = json.load(f)

    ks = data["knob_schema"]
    assert ks["nuke_version"] == "16.0v4"
    assert ks["script_hash"] == "sha256:new"
    assert "Grade1" in ks["nodes"]
    assert "OldNode" not in ks["nodes"]
