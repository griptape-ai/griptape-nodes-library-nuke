"""Low-level TCL/gizmo text writer.

This module centralizes all string-formatting details of the Nuke ``.gizmo``
file format in one place. Callers work with Python values; this class handles
TCL syntax, quoting, and indentation so that errors in the format are easy to
find and fix.

Usage::

    w = GizmoWriter()
    w.begin_gizmo("my_workflow", tile_color="0xff9900ff")
    w.add_tab("griptape_tab", label="My Workflow")
    w.add_divider("_inputs_divider", label="Inputs")
    w.add_string_knob("prompt", label="Prompt")
    w.add_divider("_run_divider", label="")
    w.add_pyscript_knob("run_workflow", label="Run Workflow", python_code="print('hi')")
    w.end_gizmo_header()
    w.begin_internal_graph()
    w.add_input_node("Input1", xpos=0, ypos=-100)
    w.add_output_node("Output1", xpos=0, ypos=100)
    w.end_group()
    text = w.render()
"""

from __future__ import annotations


class NukeKnobType:
    """Nuke knob type IDs used in addUserKnob directives.

    These integer IDs correspond to Nuke's internal knob class identifiers and are
    stable across Nuke versions. They are used in the TCL gizmo format as the first
    argument to addUserKnob, e.g. ``addUserKnob {1 my_knob l "My Knob"}``.
    """

    STRING = 1
    FILE = 2
    INT = 3
    ENUMERATION = 4
    BOOL = 6
    DOUBLE = 7
    PYSCRIPT = 22
    TAB = 20
    DIVIDER = 26
    MULTILINE_STRING = 28


def _tcl_escape(code: str) -> str:
    """Escape a Python code string for embedding inside a TCL double-quoted string.

    In Nuke's gizmo format, the T value of a PyScript_Knob is a TCL double-quoted
    string where: ``\\`` -> literal backslash, ``\\"`` -> literal quote, ``\\n`` ->
    newline. Dollar signs and brackets are safe inside double-quotes as long as
    the enclosed content does not use TCL variables or command substitution, which
    our generated Python does not.
    """
    code = code.replace("\\", "\\\\")
    code = code.replace('"', '\\"')
    code = code.replace("\n", "\\n")
    return code


def _tcl_escape_literal(text: str) -> str:
    """Escape a literal knob value or tooltip so TCL stores it verbatim instead of evaluating it."""
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("[", "\\[")
    return text.replace("$", "\\$")


class GizmoWriter:
    """Builds Nuke ``.gizmo`` file content line by line.

    All methods append to an internal line buffer. Call ``render()`` at the end
    to get the complete file content as a string.
    """

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._gizmo_name: str = ""
        self._knobs: list[tuple[int, str]] = []

    @property
    def gizmo_name(self) -> str:
        return self._gizmo_name

    @property
    def knobs(self) -> list[tuple[int, str]]:
        return list(self._knobs)

    # -- Gizmo header / footer --

    def begin_gizmo(self, name: str, tile_color: str = "0xff9900ff") -> None:
        """Open the top-level ``Gizmo { ... }`` block."""
        self._gizmo_name = name
        self._lines.append("Gizmo {")
        self._lines.append(f" name {name}")
        self._lines.append(f" tile_color {tile_color}")
        self._lines.append("")

    def set_knob_changed(self, python_code: str) -> None:
        """Set a knobChanged callback on the Gizmo block.

        Must be called between ``begin_gizmo()`` and ``end_gizmo_header()``.
        Nuke fires the callback whenever any knob on the node changes;
        the code should check ``nuke.thisKnob().name()`` to filter events.
        """
        escaped = _tcl_escape(python_code)
        self._lines.append(f' knobChanged "{escaped}"')

    def end_gizmo_header(self) -> None:
        """Close the ``Gizmo { ... }`` knob block (does NOT end the group)."""
        self._lines.append("}")

    def end_group(self) -> None:
        """Emit ``end_group`` — the final line of a ``.gizmo`` file."""
        self._lines.append("end_group")

    # -- Tab and divider knobs --

    def add_tab(self, knob_name: str, label: str) -> None:
        """Add a tab knob (creates a new properties panel tab)."""
        self._knobs.append((NukeKnobType.TAB, knob_name))
        self._lines.append(f' addUserKnob {{{NukeKnobType.TAB} {knob_name} l "{label}"}}')

    def add_divider(self, knob_name: str, label: str, flags: str = "+STARTLINE") -> None:
        """Add a horizontal divider / section label."""
        self._knobs.append((NukeKnobType.DIVIDER, knob_name))
        if flags:
            self._lines.append(f' addUserKnob {{{NukeKnobType.DIVIDER} {knob_name} l "{label}" {flags}}}')
        else:
            self._lines.append(f' addUserKnob {{{NukeKnobType.DIVIDER} {knob_name} l "{label}"}}')

    # -- Value knobs --

    def add_string_knob(
        self, knob_name: str, label: str, default: str | None = None, flags: str = "", tooltip: str | None = None
    ) -> None:
        """Add a single-line string knob."""
        self._knobs.append((NukeKnobType.STRING, knob_name))
        tooltip_part = f' t "{_tcl_escape_literal(tooltip)}"' if tooltip else ""
        flag_suffix = f" {flags}" if flags else ""
        self._lines.append(f' addUserKnob {{{NukeKnobType.STRING} {knob_name} l "{label}"{tooltip_part}{flag_suffix}}}')
        if default is not None:
            self._lines.append(f' {knob_name} "{_tcl_escape_literal(default)}"')

    def add_file_knob(
        self, knob_name: str, label: str, default: str | None = None, flags: str = "", tooltip: str | None = None
    ) -> None:
        """Add a file-browser knob."""
        self._knobs.append((NukeKnobType.FILE, knob_name))
        tooltip_part = f' t "{_tcl_escape_literal(tooltip)}"' if tooltip else ""
        flag_suffix = f" {flags}" if flags else ""
        self._lines.append(f' addUserKnob {{{NukeKnobType.FILE} {knob_name} l "{label}"{tooltip_part}{flag_suffix}}}')
        if default is not None:
            self._lines.append(f' {knob_name} "{_tcl_escape_literal(default)}"')

    def add_bool_knob(self, knob_name: str, label: str, default: bool | None = None) -> None:
        """Add a checkbox (boolean) knob."""
        self._knobs.append((NukeKnobType.BOOL, knob_name))
        self._lines.append(f' addUserKnob {{{NukeKnobType.BOOL} {knob_name} l "{label}"}}')
        if default is not None:
            self._lines.append(f" {knob_name} {'1' if default else '0'}")

    def add_int_knob(self, knob_name: str, label: str, default: int | None = None) -> None:
        """Add an integer knob."""
        self._knobs.append((NukeKnobType.INT, knob_name))
        self._lines.append(f' addUserKnob {{{NukeKnobType.INT} {knob_name} l "{label}"}}')
        if default is not None:
            self._lines.append(f" {knob_name} {default}")

    def add_double_knob(self, knob_name: str, label: str, default: float | None = None) -> None:
        """Add a double-precision float knob."""
        self._knobs.append((NukeKnobType.DOUBLE, knob_name))
        self._lines.append(f' addUserKnob {{{NukeKnobType.DOUBLE} {knob_name} l "{label}"}}')
        if default is not None:
            self._lines.append(f" {knob_name} {default}")

    def add_multiline_string_knob(
        self, knob_name: str, label: str, default: str | None = None, flags: str = "", tooltip: str | None = None
    ) -> None:
        """Add a multi-line text knob."""
        self._knobs.append((NukeKnobType.MULTILINE_STRING, knob_name))
        tooltip_part = f' t "{_tcl_escape_literal(tooltip)}"' if tooltip else ""
        flag_suffix = f" {flags}" if flags else ""
        self._lines.append(
            f' addUserKnob {{{NukeKnobType.MULTILINE_STRING} {knob_name} l "{label}"{tooltip_part}{flag_suffix}}}'
        )
        if default is not None:
            self._lines.append(f' {knob_name} "{_tcl_escape_literal(default)}"')

    def add_enumeration_knob(self, knob_name: str, label: str, choices: list, default_index: int | None = None) -> None:
        """Add a dropdown enumeration knob."""
        self._knobs.append((NukeKnobType.ENUMERATION, knob_name))
        choices_str = " ".join(f'"{c}"' if " " in str(c) else str(c) for c in choices)
        self._lines.append(f' addUserKnob {{{NukeKnobType.ENUMERATION} {knob_name} l "{label}" M {{{choices_str}}}}}')
        if default_index is not None:
            self._lines.append(f" {knob_name} {default_index}")

    def add_pyscript_knob(
        self, knob_name: str, label: str, python_code: str, flags: str = "+STARTLINE", tooltip: str | None = None
    ) -> None:
        """Add a PyScript button knob.

        ``python_code`` is plain Python; this method handles TCL escaping.
        """
        self._knobs.append((NukeKnobType.PYSCRIPT, knob_name))
        escaped = _tcl_escape(python_code)
        tooltip_part = f' t "{_tcl_escape_literal(tooltip)}"' if tooltip else ""
        flag_suffix = f" {flags}" if flags else ""
        self._lines.append(
            f' addUserKnob {{{NukeKnobType.PYSCRIPT} {knob_name} l "{label}"{tooltip_part} T "{escaped}"{flag_suffix}}}'
        )

    def add_invisible_string_knob(self, knob_name: str, value: str | None = None) -> None:
        """Add a hidden string knob. Omit ``value`` to leave it unset in the file."""
        self._knobs.append((NukeKnobType.STRING, knob_name))
        self._lines.append(f' addUserKnob {{{NukeKnobType.STRING} {knob_name} l "" +INVISIBLE}}')
        if value is not None:
            self._lines.append(f" {knob_name} {value}")

    # -- Internal graph nodes --

    def begin_internal_graph(self) -> None:
        """No-op marker for readability — internal graph nodes are emitted after end_gizmo_header."""

    def add_input_node(self, name: str, xpos: int, ypos: int) -> None:
        """Add an Input node to the internal graph."""
        self._lines.append(" Input {")
        self._lines.append("  inputs 0")
        self._lines.append(f"  name {name}")
        self._lines.append(f"  xpos {xpos}")
        self._lines.append(f"  ypos {ypos}")
        self._lines.append(" }")

    def add_read_node(self, name: str, xpos: int, ypos: int, file_expression: str | None = None) -> None:
        """Add a Read node to the internal graph.

        Args:
            name: Nuke node name (e.g. ``GEN_READ_image``).
            xpos: Horizontal position in the node graph.
            ypos: Vertical position in the node graph.
            file_expression: When provided, the Read node's ``file`` knob is set
                to a live TCL expression ``[value <file_expression>]`` rather than
                an empty literal.  Use this to link the Read to a persistent
                top-level user knob so the path survives save/reload and copy-paste.
                Example: ``"parent.image_out"``.
        """
        self._lines.append(" Read {")
        self._lines.append("  inputs 0")
        self._lines.append(f"  name {name}")
        if file_expression is not None:
            # The leading backslash prevents TCL from evaluating [value …] at
            # parse time; Nuke stores it as a live expression knob instead.
            self._lines.append(f'  file "\\[value {file_expression}]"')
        else:
            self._lines.append('  file ""')
        self._lines.append(f"  xpos {xpos}")
        self._lines.append(f"  ypos {ypos}")
        self._lines.append(" }")

    def add_output_node(self, name: str, xpos: int, ypos: int, no_inputs: bool = False) -> None:
        """Add an Output node to the internal graph."""
        self._lines.append(" Output {")
        if no_inputs:
            self._lines.append("  inputs 0")
        self._lines.append(f"  name {name}")
        self._lines.append(f"  xpos {xpos}")
        self._lines.append(f"  ypos {ypos}")
        self._lines.append(" }")

    def add_switch_node(self, name: str, num_inputs: int, xpos: int, ypos: int, which: int = 0) -> None:
        """Add a Switch node to the internal graph.

        ``which`` is the initial input index (0-based). The knobChanged
        callback on the parent gizmo is responsible for updating this at
        runtime when the user changes the active output selector.
        """
        self._lines.append(" Switch {")
        self._lines.append(f"  inputs {num_inputs}")
        self._lines.append(f"  which {which}")
        self._lines.append(f"  name {name}")
        self._lines.append(f"  xpos {xpos}")
        self._lines.append(f"  ypos {ypos}")
        self._lines.append(" }")

    # -- Render --

    def render(self) -> str:
        """Return the complete gizmo text, terminated with a newline."""
        return "\n".join(self._lines) + "\n"
