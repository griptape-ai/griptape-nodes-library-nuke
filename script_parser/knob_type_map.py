from __future__ import annotations

# Nuke knob class → Griptape parameter type string (PRD F5.1).
# Color_Knob / XY_Knob map to "str" because the canvas has no native
# colour-swatch or coordinate-pair widget; callers should document the
# expected JSON format in the tooltip.
_MAP: dict[str, str] = {
    "Double_Knob": "float",
    "Int_Knob": "int",
    "Bool_Knob": "bool",
    "Boolean_Knob": "bool",  # alias used by Nuke 15/16 in practice
    "String_Knob": "str",
    "Enumeration_Knob": "str",
    "File_Knob": "str",
    "Color_Knob": "str",
    "AColor_Knob": "str",  # RGBA colour knob alias (Nuke 16 fixtures)
    "XY_Knob": "str",
    "Array_Knob": "float",  # generic numeric (gain, gamma, saturation, …)
}


def griptape_type_for_knob(nuke_knob_class: str) -> str:
    """Return the Griptape parameter type string for a Nuke knob class name."""
    return _MAP.get(nuke_knob_class, "str")


def resolve_exposed_knob_type(
    target_node: str,
    target_knob: str,
    knob_schema: dict[str, dict] | None,
) -> str:
    """Return the Griptape type for an exposed knob by looking it up in knob_schema.

    knob_schema is the dict returned by read_knob_schema() — keyed by node name,
    each value has a "knobs" dict with per-knob metadata including "type".
    Returns "str" when schema is absent or the node/knob cannot be found.
    """
    if knob_schema is None:
        return "str"
    nuke_class: str = knob_schema.get(target_node, {}).get("knobs", {}).get(target_knob, {}).get("type", "")
    return griptape_type_for_knob(nuke_class)
