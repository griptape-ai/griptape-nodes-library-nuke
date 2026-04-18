"""Offline structural validator for generated .gizmo files.

Validates that a generated ``.gizmo`` text has the correct structure without
requiring a Nuke installation. Catches formatting errors before the file is
written to disk.

Usage::

    from publish_gizmo.gizmo_validator import GizmoValidationError, validate_gizmo_text

    try:
        validate_gizmo_text(gizmo_text)
    except GizmoValidationError as exc:
        print(f"Invalid gizmo: {exc}")
"""
# TODO: Update to use Pydantic Schema, instead of text parser. https://github.com/griptape-ai/griptape-nodes-library-nuke/issues/27

from __future__ import annotations

import re

from publish_gizmo.gizmo_writer import NukeKnobType

# All valid knob type IDs used in addUserKnob directives
_VALID_KNOB_TYPE_IDS: frozenset[int] = frozenset(v for k, v in vars(NukeKnobType).items() if not k.startswith("_"))

# Knobs the gizmo must always contain
_REQUIRED_KNOB_NAMES: frozenset[str] = frozenset({"_companion_dir", "run_workflow", "output_dir"})


class GizmoValidationError(Exception):
    """Raised when a generated gizmo text fails structural validation."""


def validate_gizmo_text(text: str) -> None:
    """Validate the structural correctness of a generated ``.gizmo`` text.

    Checks:
    - File starts with ``Gizmo {`` and ends with ``end_group``
    - All ``addUserKnob`` directives reference a valid knob type ID
    - Required knobs are present (``_companion_dir``, ``run_workflow``, ``output_dir``)
    - Top-level curly braces are balanced

    Raises:
        GizmoValidationError: if any check fails.
    """
    _check_open_and_close(text)
    _check_brace_balance(text)
    _check_knob_type_ids(text)
    _check_required_knobs(text)


def _check_open_and_close(text: str) -> None:
    lines = text.splitlines()
    if not lines:
        raise GizmoValidationError("Gizmo text is empty.")

    if not lines[0].startswith("Gizmo {"):
        raise GizmoValidationError(f"Expected first line to start with 'Gizmo {{', got: {lines[0]!r}")

    last_nonempty = next((line for line in reversed(lines) if line.strip()), None)
    if last_nonempty != "end_group":
        raise GizmoValidationError(f"Expected last non-empty line to be 'end_group', got: {last_nonempty!r}")


def _check_brace_balance(text: str) -> None:
    """Check that all curly braces are balanced in the gizmo text.

    The gizmo format uses ``{`` and ``}`` extensively in addUserKnob directives.
    Balanced braces ensure the TCL parser will not choke on unclosed groups.
    """
    depth = 0
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                context = text[max(0, i - 40) : i + 40].replace("\n", "\\n")
                raise GizmoValidationError(f"Unmatched '}}' at position {i}. Context: {context!r}")
    if depth != 0:
        raise GizmoValidationError(f"Unbalanced braces: {depth} unclosed '{{' remaining at end of file.")


def _check_knob_type_ids(text: str) -> None:
    """Verify every addUserKnob directive uses a known knob type ID."""
    pattern = re.compile(r"addUserKnob\s*\{(\d+)\s")
    for match in pattern.finditer(text):
        type_id = int(match.group(1))
        if type_id not in _VALID_KNOB_TYPE_IDS:
            start = match.start()
            snippet = text[start : start + 60].replace("\n", "\\n")
            raise GizmoValidationError(
                f"Unknown knob type ID {type_id} in addUserKnob directive: {snippet!r}. "
                f"Valid IDs: {sorted(_VALID_KNOB_TYPE_IDS)}"
            )


def _check_required_knobs(text: str) -> None:
    """Verify that all required knob names are declared in the gizmo."""
    for knob_name in _REQUIRED_KNOB_NAMES:
        pattern = re.compile(rf"\baddUserKnob\s*\{{\d+\s+{re.escape(knob_name)}\b")
        if not pattern.search(text):
            raise GizmoValidationError(
                f"Required knob '{knob_name}' not found in gizmo. Required knobs: {sorted(_REQUIRED_KNOB_NAMES)}"
            )
