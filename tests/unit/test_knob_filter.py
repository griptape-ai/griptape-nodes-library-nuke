from __future__ import annotations

from script_parser.knob_filter import KnobFilter, filter_nodes, get_filter

_BASELINE = KnobFilter(
    excluded_types=frozenset({"Obsolete_Knob"}),
    excluded_name_suffixes=("_panelDropped",),
)

_NODES_WITH_NOISE = {
    "Write1": {
        "class": "Write",
        "knobs": {
            "file": {"type": "File_Knob", "label": "", "value": "", "default": None, "is_default": None},
            "layer": {"type": "Obsolete_Knob", "label": "", "value": None, "default": None, "is_default": None},
            "color0": {"type": "AColor_Knob", "label": "color 0", "value": 1.0, "default": 1.0, "is_default": None},
            "color0_panelDropped": {
                "type": "Boolean_Knob",
                "label": "panel dropped state",
                "value": False,
                "default": 0.0,
                "is_default": None,
            },
            "disable": {"type": "Disable_Knob", "label": "Disable", "value": False, "default": 0.0, "is_default": None},
        },
    }
}


def test_obsolete_knob_type_is_excluded() -> None:
    result = filter_nodes(_NODES_WITH_NOISE, _BASELINE)
    assert "layer" not in result["Write1"]["knobs"]


def test_panel_dropped_suffix_is_excluded() -> None:
    result = filter_nodes(_NODES_WITH_NOISE, _BASELINE)
    assert "color0_panelDropped" not in result["Write1"]["knobs"]


def test_normal_knob_passes_through() -> None:
    result = filter_nodes(_NODES_WITH_NOISE, _BASELINE)
    knobs = result["Write1"]["knobs"]
    assert "file" in knobs
    assert "color0" in knobs
    assert "disable" in knobs


def test_filter_nodes_returns_copy_not_mutation() -> None:
    import copy

    original = copy.deepcopy(_NODES_WITH_NOISE)
    filter_nodes(_NODES_WITH_NOISE, _BASELINE)
    assert _NODES_WITH_NOISE == original


def test_get_filter_parses_version_string() -> None:
    f = get_filter("16.0v4")
    assert isinstance(f, KnobFilter)
    assert "Obsolete_Knob" in f.excluded_types


def test_get_filter_falls_back_to_baseline_for_unknown_version() -> None:
    f = get_filter("unknown")
    assert isinstance(f, KnobFilter)
    assert "Obsolete_Knob" in f.excluded_types


def test_get_filter_accepts_integer_version() -> None:
    f = get_filter(15)
    assert isinstance(f, KnobFilter)


def test_get_filter_for_future_version_uses_latest_matching_entry(monkeypatch) -> None:
    from script_parser import knob_filter as kf

    extra_filter = KnobFilter(
        excluded_types=frozenset({"Obsolete_Knob", "Future_Knob"}),
        excluded_name_suffixes=("_panelDropped",),
    )
    patched = {0: _BASELINE, 15: extra_filter}
    monkeypatch.setattr(kf, "_FILTERS", patched)

    f17 = kf.get_filter(17)
    assert f17 is extra_filter

    f14 = kf.get_filter(14)
    assert f14 is _BASELINE


def test_should_exclude_returns_true_for_excluded_type() -> None:
    assert _BASELINE.should_exclude("layer", "Obsolete_Knob")


def test_should_exclude_returns_true_for_excluded_suffix() -> None:
    assert _BASELINE.should_exclude("color0_panelDropped", "Boolean_Knob")


def test_should_exclude_returns_false_for_normal_knob() -> None:
    assert not _BASELINE.should_exclude("disable", "Disable_Knob")
