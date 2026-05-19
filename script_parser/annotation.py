from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GriptapeAnnotation:
    node_name: str
    role: str
    gt_name: str
    gt_type: str
    gt_label: str | None = None


@dataclass
class ExposedKnob:
    """A knob promoted to the Griptape node interface via gt_expose_* annotation."""

    source_node: str  # node bearing the gt_expose_* knob
    knob_ref: str  # full "TargetNode.knobName" reference
    target_node: str  # derived: part before the first dot
    target_knob: str  # derived: part after the first dot
    param_name: str  # Griptape parameter name: "{target_node}_{target_knob}"
    knob_type: str | None = None  # Nuke knob class (e.g. "Double_Knob"), if recorded
