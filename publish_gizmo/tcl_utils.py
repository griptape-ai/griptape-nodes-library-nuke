"""TCL-expression resolution for gizmo knobs, shared by the bundled run_button.

This module is copied into the gizmo companion directory at publish time and
imported by ``run_button.py`` (which is exec'd, not imported). Keeping the logic
here — rather than inline in the exec'd script — lets the unit tests import it
normally instead of source-parsing ``run_button.py``.

Runtime dependency: ``nuke`` is provided by the Nuke interpreter. Tests inject a
fake ``nuke`` via the module namespace.
"""

from __future__ import annotations

try:
    import nuke  # type: ignore[import-not-found]
except ImportError:  # unit tests / non-Nuke environments inject their own
    nuke = None  # type: ignore[assignment]

# Prefix for the hidden companion knob that stores a Link button's TCL expression.
# Must stay in sync with GT_EXPR_PREFIX in constants.py (which is not copied into
# the bundle, so it cannot be imported here at runtime).
GT_EXPR_PREFIX = "_gt_expr_"


def _expand_tcl(n, knob_name: str, raw):
    """Resolve a knob's runtime value, preferring its stored Link expression.

    A knob linked via the gizmo's Link button stores its TCL expression in a
    hidden ``_gt_expr_<knob>`` companion knob while the visible field shows the
    evaluated value; re-evaluating the expression here keeps time-dependent
    links (e.g. [frame]) fresh. Hand-typed [bracket] text in the visible field
    is expanded via TCL's ``value`` command, which evaluates in the knob's own
    node context so ``this`` resolves to the gizmo instance. Values that aren't
    valid TCL (e.g. JSON arrays) raise and fall back to the raw text.

    An expression that legitimately evaluates to an empty string returns ``""``
    (not the stale display text): only an evaluation *error* falls back to raw.
    """
    expr_knob = n.knob(GT_EXPR_PREFIX + knob_name)
    if expr_knob is not None and expr_knob.getText():
        try:
            expanded = expr_knob.evaluate()
        except Exception:  # noqa: BLE001
            expanded = None
        if expanded is not None:
            return expanded
    if not isinstance(raw, str) or "[" not in raw:
        return raw
    try:
        # nuke is always present at runtime (this branch only runs inside Nuke);
        # the module-level fallback to None exists solely for unit-test injection.
        expanded = nuke.tcl("value", n.fullName() + "." + knob_name)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return raw
    return expanded if expanded is not None else raw
