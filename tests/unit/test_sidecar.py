from __future__ import annotations

import os

from script_parser.annotation import ExposedKnob, GriptapeAnnotation
from script_parser.sidecar import compute_script_hash, read_sidecar, write_sidecar

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SCRIPT_PATH = os.path.join(FIXTURES, "annotated_read_write.nk")


def _make_annotations() -> list[GriptapeAnnotation]:
    return [
        GriptapeAnnotation(
            node_name="GradeInput",
            role="input",
            gt_name="source_image",
            gt_type="ImageArtifact",
            gt_label="Source Image",
        ),
        GriptapeAnnotation(
            node_name="GradeOutput",
            role="output",
            gt_name="graded_image",
            gt_type="ImageArtifact",
        ),
    ]


def test_compute_script_hash_returns_sha256_prefix() -> None:
    h = compute_script_hash(SCRIPT_PATH)
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_sidecar_round_trips_annotations(tmp_path) -> None:
    sidecar = str(tmp_path / "annotated_read_write.gt.json")
    anns = _make_annotations()

    write_sidecar(sidecar, SCRIPT_PATH, anns)
    loaded, _expose_knobs, is_stale = read_sidecar(sidecar, SCRIPT_PATH)

    assert not is_stale
    assert len(loaded) == len(anns)

    by_name = {a.node_name: a for a in loaded}
    assert by_name["GradeInput"].role == "input"
    assert by_name["GradeInput"].gt_name == "source_image"
    assert by_name["GradeInput"].gt_type == "ImageArtifact"
    assert by_name["GradeInput"].gt_label == "Source Image"
    assert by_name["GradeOutput"].role == "output"
    assert by_name["GradeOutput"].gt_name == "graded_image"


def test_sidecar_returns_not_stale_when_hash_matches(tmp_path) -> None:
    sidecar = str(tmp_path / "test.gt.json")
    write_sidecar(sidecar, SCRIPT_PATH, _make_annotations())
    _anns, _expose, is_stale = read_sidecar(sidecar, SCRIPT_PATH)
    assert not is_stale


def test_sidecar_warns_when_script_hash_changed(tmp_path) -> None:
    modified_script = str(tmp_path / "modified.nk")
    sidecar = str(tmp_path / "modified.gt.json")

    with open(SCRIPT_PATH, encoding="utf-8") as f:
        original = f.read()
    with open(modified_script, "w", encoding="utf-8") as f:
        f.write(original)

    write_sidecar(sidecar, modified_script, _make_annotations())

    # Modify the script after writing the sidecar
    with open(modified_script, "a", encoding="utf-8") as f:
        f.write("# modified\n")

    _anns, _expose, is_stale = read_sidecar(sidecar, modified_script)
    assert is_stale


def test_sidecar_round_trips_expose_knobs(tmp_path) -> None:
    sidecar = str(tmp_path / "expose.gt.json")
    expose_knobs = [
        ExposedKnob(
            source_node="Grade1",
            knob_ref="Grade1.white",
            target_node="Grade1",
            target_knob="white",
            param_name="Grade1_white",
        )
    ]

    write_sidecar(sidecar, SCRIPT_PATH, [], expose_knobs=expose_knobs)
    _anns, loaded_expose, is_stale = read_sidecar(sidecar, SCRIPT_PATH)

    assert not is_stale
    assert len(loaded_expose) == 1
    ek = loaded_expose[0]
    assert ek.knob_ref == "Grade1.white"
    assert ek.target_node == "Grade1"
    assert ek.target_knob == "white"
    assert ek.param_name == "Grade1_white"


def test_write_sidecar_creates_file_when_absent(tmp_path) -> None:
    sidecar = str(tmp_path / "new.gt.json")
    write_sidecar(sidecar, SCRIPT_PATH, [])
    assert os.path.exists(sidecar)


def test_sidecar_round_trips_expose_knob_type(tmp_path) -> None:
    sidecar = str(tmp_path / "expose_typed.gt.json")
    expose_knobs = [
        ExposedKnob(
            source_node="Grade1",
            knob_ref="Grade1.gain",
            target_node="Grade1",
            target_knob="gain",
            param_name="Grade1_gain",
            knob_type="Double_Knob",
        )
    ]

    write_sidecar(sidecar, SCRIPT_PATH, [], expose_knobs=expose_knobs)
    _anns, loaded_expose, _ = read_sidecar(sidecar, SCRIPT_PATH)

    assert len(loaded_expose) == 1
    assert loaded_expose[0].knob_type == "Double_Knob"


def test_sidecar_reads_expose_knob_type_written_by_plugin(tmp_path) -> None:
    """read_sidecar propagates "type" field written by the Nuke plugin."""
    import json

    sidecar = str(tmp_path / "plugin_written.gt.json")
    data = {
        "schema": "griptape-nuke-annotations/1.0",
        "script": "test.nk",
        "script_hash": compute_script_hash(SCRIPT_PATH),
        "annotations": [
            {
                "node": "Grade1",
                "gt_expose": [
                    {"knob": "Grade1.gain", "type": "Double_Knob"},
                    {"knob": "Grade1.enable", "type": "Boolean_Knob"},
                    {"knob": "Grade1.label"},  # no type — older sidecar
                ],
            }
        ],
    }
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(data, f)

    _anns, expose_knobs, _ = read_sidecar(sidecar, SCRIPT_PATH)

    by_knob = {ek.target_knob: ek for ek in expose_knobs}
    assert by_knob["gain"].knob_type == "Double_Knob"
    assert by_knob["enable"].knob_type == "Boolean_Knob"
    assert by_knob["label"].knob_type is None


def test_write_sidecar_preserves_knob_schema(tmp_path) -> None:
    from script_parser.sidecar import write_knob_schema

    sidecar = str(tmp_path / "shot.gt.json")
    nodes = {"Grade1": {"class": "Grade", "knobs": {}}}
    write_knob_schema(sidecar, "16.0v4", "sha256:abc", nodes)

    write_sidecar(sidecar, SCRIPT_PATH, [])

    import json

    with open(sidecar, encoding="utf-8") as f:
        data = json.load(f)
    assert "knob_schema" in data
    assert data["knob_schema"]["nuke_version"] == "16.0v4"


def test_sidecar_reads_expose_knobs_from_multiple_nodes_gives_unique_param_names(tmp_path) -> None:
    import json

    sidecar = str(tmp_path / "multi_node.gt.json")
    data = {
        "schema": "griptape-nuke-annotations/1.0",
        "script": "test.nk",
        "script_hash": compute_script_hash(SCRIPT_PATH),
        "annotations": [
            {
                "node": "Grade_Red",
                "gt_expose": [
                    {"knob": "Grade_Red.blackpoint", "type": "AColor_Knob"},
                    {"knob": "Grade_Red.whitepoint", "type": "AColor_Knob"},
                ],
            },
            {
                "node": "Grade_Green",
                "gt_expose": [
                    {"knob": "Grade_Green.blackpoint", "type": "AColor_Knob"},
                    {"knob": "Grade_Green.whitepoint", "type": "AColor_Knob"},
                ],
            },
        ],
    }
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(data, f)

    _anns, expose_knobs, _ = read_sidecar(sidecar, SCRIPT_PATH)

    assert len(expose_knobs) == 4
    param_names = [ek.param_name for ek in expose_knobs]
    assert len(set(param_names)) == 4, f"duplicate param_names: {param_names}"
    assert "Grade_Red_blackpoint" in param_names
    assert "Grade_Red_whitepoint" in param_names
    assert "Grade_Green_blackpoint" in param_names
    assert "Grade_Green_whitepoint" in param_names


def test_read_sidecar_ignores_gt_expose_on_io_annotated_nodes(tmp_path) -> None:
    """gt_expose on a node with gt_role must not produce ExposedKnob objects."""
    import json

    sidecar = str(tmp_path / "mixed.gt.json")
    data = {
        "schema": "griptape-nuke-annotations/1.0",
        "script": "test.nk",
        "script_hash": compute_script_hash(SCRIPT_PATH),
        "annotations": [
            {
                "node": "Read1",
                "gt_role": "input",
                "gt_name": "read",
                "gt_type": "ImageArtifact",
                # hand-authored sidecar that also has gt_expose — must be ignored
                "gt_expose": [{"knob": "Read1.file", "type": "File_Knob"}],
            },
            {
                "node": "Grade1",
                "gt_expose": [{"knob": "Grade1.gain", "type": "Double_Knob"}],
            },
        ],
    }
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(data, f)

    anns, expose_knobs, _ = read_sidecar(sidecar, SCRIPT_PATH)

    assert len(anns) == 1
    assert anns[0].node_name == "Read1"
    # Only the Grade1 expose knob should be returned — not the Read1 one
    assert len(expose_knobs) == 1
    assert expose_knobs[0].target_knob == "gain"
