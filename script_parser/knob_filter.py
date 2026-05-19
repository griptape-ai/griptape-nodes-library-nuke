from __future__ import annotations

import re
from dataclasses import dataclass

_VERSION_RE = re.compile(r"^(\d+)")


@dataclass(frozen=True)
class KnobFilter:
    """Rules for excluding noise knobs from the knob_schema section of a sidecar."""

    excluded_types: frozenset[str]
    excluded_name_suffixes: tuple[str, ...]

    def should_exclude(self, name: str, knob_type: str) -> bool:
        if knob_type in self.excluded_types:
            return True
        return any(name.endswith(suffix) for suffix in self.excluded_name_suffixes)


# Keyed by Nuke major version int. Key 0 is the baseline applied to all versions.
# Add higher-numbered keys to override or extend behaviour for specific versions.
_FILTERS: dict[int, KnobFilter] = {
    0: KnobFilter(
        excluded_types=frozenset({"Obsolete_Knob"}),
        excluded_name_suffixes=("_panelDropped",),
    ),
}


def get_filter(nuke_version: str | int) -> KnobFilter:
    """Return the KnobFilter for the given Nuke version.

    Accepts a version string like "16.0v4" or an integer major version.
    Falls back to the baseline (key 0) when the version is unparseable or below all
    defined keys.
    """
    if isinstance(nuke_version, int):
        major = nuke_version
    else:
        m = _VERSION_RE.match(str(nuke_version))
        major = int(m.group(1)) if m else 0

    matching = [k for k in _FILTERS if k <= major]
    key = max(matching) if matching else 0
    return _FILTERS.get(key, _FILTERS[0])


def filter_nodes(nodes: dict[str, dict], knob_filter: KnobFilter) -> dict[str, dict]:
    """Return a filtered copy of the nodes dict with noise knobs removed."""
    result: dict[str, dict] = {}
    for node_name, node_data in nodes.items():
        knobs = node_data.get("knobs", {})
        filtered_knobs = {
            name: info for name, info in knobs.items() if not knob_filter.should_exclude(name, info.get("type", ""))
        }
        result[node_name] = {**node_data, "knobs": filtered_knobs}
    return result
