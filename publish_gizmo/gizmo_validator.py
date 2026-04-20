"""Offline structural validator for generated .gizmo files.

Validates that a ``GizmoWriter`` instance has the correct structure without
requiring a Nuke installation. Catches semantic errors before the file is
written to disk.

Usage::

    from publish_gizmo.gizmo_validator import GizmoValidationError, validate_gizmo
    from publish_gizmo.gizmo_writer import GizmoWriter

    w = GizmoWriter()
    # ... build the gizmo ...
    try:
        validate_gizmo(w)
    except GizmoValidationError as exc:
        print(f"Invalid gizmo: {exc}")
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError, model_validator

from publish_gizmo.gizmo_writer import GizmoWriter, NukeKnobType

_VALID_KNOB_TYPE_IDS: frozenset[int] = frozenset(v for k, v in vars(NukeKnobType).items() if not k.startswith("_"))
_REQUIRED_KNOB_NAMES: frozenset[str] = frozenset({"_companion_dir", "run_workflow", "output_dir"})


class GizmoValidationError(Exception):
    """Raised when a generated gizmo fails structural validation."""


class _GizmoKnob(BaseModel):
    type_id: int
    name: str

    @model_validator(mode="after")
    def check_valid_type_id(self) -> _GizmoKnob:
        if self.type_id not in _VALID_KNOB_TYPE_IDS:
            raise ValueError(
                f"Unknown knob type ID {self.type_id} for knob '{self.name}'. "
                f"Valid IDs: {sorted(_VALID_KNOB_TYPE_IDS)}"
            )
        return self


class _GizmoModel(BaseModel):
    name: str
    knobs: list[_GizmoKnob]

    @model_validator(mode="after")
    def check_required_knobs(self) -> _GizmoModel:
        found = {k.name for k in self.knobs}
        missing = _REQUIRED_KNOB_NAMES - found
        if missing:
            raise ValueError(
                f"Missing required knobs: {sorted(missing)}. Required: {sorted(_REQUIRED_KNOB_NAMES)}"
            )
        return self


def validate_gizmo(writer: GizmoWriter) -> None:
    """Validate the structural correctness of a ``GizmoWriter`` before rendering.

    Checks:
    - All ``addUserKnob`` directives reference a valid knob type ID
    - Required knobs are present (``_companion_dir``, ``run_workflow``, ``output_dir``)

    Structural correctness (balanced braces, ``Gizmo {`` / ``end_group`` delimiters)
    is guaranteed by construction via ``GizmoWriter``.

    Raises:
        GizmoValidationError: if any check fails.
    """
    try:
        _GizmoModel.model_validate({
            "name": writer.gizmo_name,
            "knobs": [{"type_id": type_id, "name": name} for type_id, name in writer.knobs],
        })
    except ValidationError as exc:
        messages = "; ".join(err["msg"] for err in exc.errors())
        raise GizmoValidationError(messages) from exc
