"""Low-level .nk file writer for Nuke LiveGroup publishing.

Analogous to publish_gizmo/gizmo_writer.py but generates the contents of a
LiveGroup's source .nk file rather than a standalone .gizmo file.

The key structural difference from a .gizmo:
- No ``Gizmo { }`` or ``LiveGroup { }`` wrapper block.
- ``addUserKnob`` directives at the top of the file are applied to the LiveGroup
  container node itself when Nuke loads the file.
- Internal graph nodes (Input, Read, Output) are written as bare top-level blocks.

Usage::

    w = NkWriter()
    # Knob directives applied to the LiveGroup container
    w.add_tab("griptape_tab", label="My Workflow")
    w.add_string_knob("prompt", label="Prompt")
    w.add_pyscript_knob("run_workflow", label="Run Workflow", python_code="print('hi')")
    w.add_invisible_string_knob("_companion_dir", value="/path/to/dir")
    # Internal graph nodes
    w.add_input_node("Input1", xpos=0, ypos=-100)
    w.add_read_node("GEN_READ_result", xpos=200, ypos=0)
    w.add_output_node("Output1", xpos=200, ypos=100)
    text = w.render()
"""

from __future__ import annotations


class NukeKnobType:
    """Nuke knob type IDs used in addUserKnob directives.

    These integer IDs correspond to Nuke's internal knob class identifiers and are
    stable across Nuke versions. They match the same constants in gizmo_writer.py.
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
    """Escape a Python code string for embedding inside a TCL double-quoted string."""
    code = code.replace("\\", "\\\\")
    code = code.replace('"', '\\"')
    code = code.replace("\n", "\\n")
    return code


class NkWriter:
    """Builds Nuke ``.nk`` LiveGroup file content line by line.

    All methods append to an internal line buffer. Call ``render()`` at the end
    to get the complete file content as a string.

    Unlike GizmoWriter, there is no begin_gizmo/end_gizmo_header wrapper.
    Knob directives written before any node blocks are applied by Nuke to the
    LiveGroup container node itself.
    """

    def __init__(self) -> None:
        self._lines: list[str] = []

    # -- Knob directives (applied to the LiveGroup container) --

    def add_tab(self, knob_name: str, label: str) -> None:
        """Add a tab knob (creates a new properties panel tab)."""
        self._lines.append(f'addUserKnob {{{NukeKnobType.TAB} {knob_name} l "{label}"}}')

    def add_divider(self, knob_name: str, label: str, flags: str = "+STARTLINE") -> None:
        """Add a horizontal divider / section label."""
        if flags:
            self._lines.append(f'addUserKnob {{{NukeKnobType.DIVIDER} {knob_name} l "{label}" {flags}}}')
        else:
            self._lines.append(f'addUserKnob {{{NukeKnobType.DIVIDER} {knob_name} l "{label}"}}')

    def add_string_knob(self, knob_name: str, label: str, default: str | None = None, flags: str = "") -> None:
        """Add a single-line string knob."""
        flag_suffix = f" {flags}" if flags else ""
        self._lines.append(f'addUserKnob {{{NukeKnobType.STRING} {knob_name} l "{label}"{flag_suffix}}}')
        if default is not None:
            self._lines.append(f'{knob_name} "{default}"')

    def add_file_knob(self, knob_name: str, label: str, default: str | None = None, flags: str = "") -> None:
        """Add a file-browser knob."""
        flag_suffix = f" {flags}" if flags else ""
        self._lines.append(f'addUserKnob {{{NukeKnobType.FILE} {knob_name} l "{label}"{flag_suffix}}}')
        if default is not None:
            self._lines.append(f'{knob_name} "{default}"')

    def add_bool_knob(self, knob_name: str, label: str, default: bool | None = None) -> None:
        """Add a checkbox (boolean) knob."""
        self._lines.append(f'addUserKnob {{{NukeKnobType.BOOL} {knob_name} l "{label}"}}')
        if default is not None:
            self._lines.append(f"{knob_name} {'1' if default else '0'}")

    def add_int_knob(self, knob_name: str, label: str, default: int | None = None) -> None:
        """Add an integer knob."""
        self._lines.append(f'addUserKnob {{{NukeKnobType.INT} {knob_name} l "{label}"}}')
        if default is not None:
            self._lines.append(f"{knob_name} {default}")

    def add_double_knob(self, knob_name: str, label: str, default: float | None = None) -> None:
        """Add a double-precision float knob."""
        self._lines.append(f'addUserKnob {{{NukeKnobType.DOUBLE} {knob_name} l "{label}"}}')
        if default is not None:
            self._lines.append(f"{knob_name} {default}")

    def add_multiline_string_knob(
        self, knob_name: str, label: str, default: str | None = None, flags: str = ""
    ) -> None:
        """Add a multi-line text knob."""
        flag_suffix = f" {flags}" if flags else ""
        self._lines.append(f'addUserKnob {{{NukeKnobType.MULTILINE_STRING} {knob_name} l "{label}"{flag_suffix}}}')
        if default is not None:
            self._lines.append(f'{knob_name} "{default}"')

    def add_enumeration_knob(self, knob_name: str, label: str, choices: list, default_index: int | None = None) -> None:
        """Add a dropdown enumeration knob."""
        choices_str = " ".join(f'"{c}"' if " " in str(c) else str(c) for c in choices)
        self._lines.append(f'addUserKnob {{{NukeKnobType.ENUMERATION} {knob_name} l "{label}" M {{{choices_str}}}}}')
        if default_index is not None:
            self._lines.append(f"{knob_name} {default_index}")

    def add_pyscript_knob(self, knob_name: str, label: str, python_code: str, flags: str = "+STARTLINE") -> None:
        """Add a PyScript button knob.

        ``python_code`` is plain Python; this method handles TCL escaping.
        """
        escaped = _tcl_escape(python_code)
        flag_suffix = f" {flags}" if flags else ""
        self._lines.append(
            f'addUserKnob {{{NukeKnobType.PYSCRIPT} {knob_name} l "{label}" T "{escaped}"{flag_suffix}}}'
        )

    def add_invisible_string_knob(self, knob_name: str, value: str) -> None:
        """Add a hidden string knob storing a value (no label shown)."""
        self._lines.append(f'addUserKnob {{{NukeKnobType.STRING} {knob_name} l "" +INVISIBLE}}')
        self._lines.append(f"{knob_name} {value}")

    # -- Internal graph node blocks --

    def add_input_node(self, name: str, xpos: int, ypos: int) -> None:
        """Add an Input node to the internal graph."""
        self._lines.append("Input {")
        self._lines.append(" inputs 0")
        self._lines.append(f" name {name}")
        self._lines.append(f" xpos {xpos}")
        self._lines.append(f" ypos {ypos}")
        self._lines.append("}")

    def add_read_node(self, name: str, xpos: int, ypos: int) -> None:
        """Add a Read node with an empty file path to the internal graph."""
        self._lines.append("Read {")
        self._lines.append(" inputs 0")
        self._lines.append(f" name {name}")
        self._lines.append(' file ""')
        self._lines.append(f" xpos {xpos}")
        self._lines.append(f" ypos {ypos}")
        self._lines.append("}")

    def add_output_node(self, name: str, xpos: int, ypos: int, no_inputs: bool = False) -> None:
        """Add an Output node to the internal graph."""
        self._lines.append("Output {")
        if no_inputs:
            self._lines.append(" inputs 0")
        self._lines.append(f" name {name}")
        self._lines.append(f" xpos {xpos}")
        self._lines.append(f" ypos {ypos}")
        self._lines.append("}")

    # -- Render --

    def render(self) -> str:
        """Return the complete .nk file text, terminated with a newline."""
        return "\n".join(self._lines) + "\n"
