from __future__ import annotations

import os
import re

from publish_gizmo.constants import GT_EXPR_PREFIX, OUTPUTS_DIR_NAME, RUN_BUTTON_FILENAME, versioned_node_name
from publish_gizmo.gizmo_validator import validate_gizmo
from publish_gizmo.gizmo_writer import GizmoWriter, NukeKnobType

# Parameter types that are control-flow connections, not user data knobs
_CONTROL_PARAM_TYPES = {"parametercontroltype"}

# Output params auto-added by EndNode that we don't want as gizmo knobs
_SKIP_OUTPUT_PARAM_NAMES = {"was_successful", "result_details", "exec_in", "failed"}

# Maps Griptape parameter types to Nuke knob type IDs and Nuke knob class names
_TYPE_TO_NUKE_KNOB: dict[str, tuple[int, str]] = {
    "ImageUrlArtifact": (NukeKnobType.FILE, "File_Knob"),
    "ImageArtifact": (NukeKnobType.FILE, "File_Knob"),
    "BlobArtifact": (NukeKnobType.FILE, "File_Knob"),
    "AudioArtifact": (NukeKnobType.FILE, "File_Knob"),
    "VideoUrlArtifact": (NukeKnobType.FILE, "File_Knob"),
    "VideoArtifact": (NukeKnobType.FILE, "File_Knob"),
    "TextArtifact": (NukeKnobType.MULTILINE_STRING, "String_Knob"),
    "str": (NukeKnobType.MULTILINE_STRING, "String_Knob"),
    "float": (NukeKnobType.DOUBLE, "Double_Knob"),
    "int": (NukeKnobType.INT, "Int_Knob"),
    "bool": (NukeKnobType.BOOL, "Bool_Knob"),
    "CsvArtifact": (NukeKnobType.MULTILINE_STRING, "MultiLine_String_Knob"),
    "JsonArtifact": (NukeKnobType.MULTILINE_STRING, "MultiLine_String_Knob"),
}

# File-path types that use a file browser in Nuke
_FILE_PATH_TYPES = {
    "ImageUrlArtifact",
    "ImageArtifact",
    "BlobArtifact",
    "AudioArtifact",
    "VideoUrlArtifact",
    "VideoArtifact",
}

# Types that use a multi-line text field in Nuke
_MULTILINE_TYPES = {"CsvArtifact", "JsonArtifact"}

# Media types whose outputs should be displayed in an internal Read node in Nuke
_MEDIA_OUTPUT_TYPES = {
    "ImageUrlArtifact",
    "ImageArtifact",
    "BlobArtifact",
    "AudioArtifact",
    "VideoUrlArtifact",
    "VideoArtifact",
}

# Types that render the full root frame range to a temp video (vs single-frame default)
_FRAME_RANGE_INPUT_TYPES = {"VideoUrlArtifact", "VideoArtifact"}

# All media input types that get upstream Nuke Input nodes in the gizmo
_MEDIA_INPUT_TYPES = {
    "ImageUrlArtifact",
    "ImageArtifact",
    "BlobArtifact",
    "AudioArtifact",
    "VideoUrlArtifact",
    "VideoArtifact",
}

# Naming conventions for internal Nuke nodes inside the gizmo
_READ_NODE_PREFIX = "GEN_READ"
_INPUT_NODE_PREFIX = "Input"
_OUTPUT_NODE_PREFIX = "Output"
_TEMP_FILE_PREFIX = "gt_input"

# Tooltips advertising Nuke TCL expression support (string knobs have no
# right-click "Add expression" menu, so hover hints are the discovery path)
_TCL_HINT_TOOLTIP = (
    "Supports Nuke TCL expressions in [brackets], e.g. [value this.name] or [frame]. "
    "Expressions are evaluated when the workflow runs."
)
_OUTPUT_DIR_TOOLTIP = (
    f"Directory for workflow outputs. Leave blank to save to a '{OUTPUTS_DIR_NAME}' folder next to the .nk script. "
    "A relative path is resolved against the folder containing this .nk script. "
    "Supports TCL expressions, e.g. [file dirname [value root.name]]/griptape."
)
# Static Run-tab text under the Output Directory field. The blank-field default is
# otherwise invisible until the user hovers the tooltip or finds the Outputs tab.
_OUTPUT_DIR_HELP_TEXT = f"When blank, outputs are saved to a '{OUTPUTS_DIR_NAME}' folder next to this .nk script."
_LINK_BUTTON_TOOLTIP = (
    "Link this field to the gizmo name, script folder, script name, frame, or any node.knob. "
    "The field shows the linked value; editing it by hand removes the link."
)
_COPY_LINK_TOOLTIP = (
    "Copy a [value ...] expression for this output to the clipboard. "
    "Select another node first to expression-link one of its knobs to this output directly."
)


def _output_tooltip(knob_name: str) -> str:
    """Tooltip telling users how to reference this output from other nodes.

    ``knob_name`` already carries the ``_out`` suffix (e.g. ``caption_out``),
    so the example expression uses that suffixed name even though the panel
    labels the knob without it (e.g. "Caption"). This is intentional — the
    suffixed name is exactly what the user must type in the expression.
    """
    return (
        f"Workflow output. Reference it from any other node with a TCL expression, "
        f"e.g. [value <this node's name>.{knob_name}] (note the '_out' suffix — that is the real knob name)."
    )


def _read_node_name(param_name: str) -> str:
    """Return the internal Read node name for a given media output parameter."""
    return f"{_READ_NODE_PREFIX}_{_safe_knob_name(param_name)}"


def _input_node_name(index: int) -> str:
    """Return the internal Input node name for a given index (1-based in Nuke)."""
    return f"{_INPUT_NODE_PREFIX}{index + 1}"


def _output_node_name(index: int) -> str:
    """Return the internal Output node name for a given index (1-based in Nuke)."""
    return f"{_OUTPUT_NODE_PREFIX}{index + 1}"


def _is_control_param(param_info: dict) -> bool:
    return param_info.get("type", "") in _CONTROL_PARAM_TYPES


def _safe_knob_name(name: str) -> str:
    """Convert a parameter name to a valid Nuke knob name (alphanumeric + underscore)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _output_knob_name(param_name: str) -> str:
    """Return the gizmo knob name for an output parameter.

    Output knobs are suffixed with ``_out`` to avoid name collisions when an
    input parameter shares the same name as an output parameter (e.g. a
    workflow that takes an ``image`` input and also produces an ``image``
    output).  Nuke silently skips duplicate knob names, which would leave the
    Outputs tab empty without this disambiguation.
    """
    return _safe_knob_name(param_name) + "_out"


def _label(name: str) -> str:
    """Convert a snake_case name to a human-readable label."""
    return name.replace("_", " ").title()


def _as_bool(value: object) -> bool | None:
    """Coerce a knob default to bool, or None when there is no value to write.

    None is the signal to omit the value line entirely, which leaves the knob at
    Nuke's own initial value. Dynamically added parameters carry "" rather than
    None, so an empty string must read as absent too.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
    return None


def _as_int(value: object) -> int | None:
    """Coerce a knob default to int, or None when there is no usable value."""
    # bool is an int subclass, but a checkbox value on an int knob is a type
    # mismatch rather than a 0/1 the user chose, so leave the knob alone.
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def _as_text(value: object) -> str | None:
    """Coerce a knob default to text, or None when there is no usable value.

    Only scalars are accepted. An artifact or container would stringify to a Python
    repr, which is worse in the knob than leaving it empty — and the writer's TCL
    escaping requires a str.
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)):
        return str(value)
    return None


def _as_float(value: object) -> float | None:
    """Coerce a knob default to float, or None when there is no usable value."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _build_knob_changed_code() -> str:
    """Return Python code for the gizmo's knobChanged callback.

    Handles three cases: on ``active_output`` change, flip the internal
    SwitchOutput (a no-op guarded by ``nuke.toNode`` when the gizmo has no
    such node, e.g. a single-output gizmo); on rename, re-evaluate linked
    fields so they display the current value; on a manual edit of a linked
    field, clear its stored expression (unlink).
    """
    prefix = GT_EXPR_PREFIX
    prefix_len = len(GT_EXPR_PREFIX)
    return f"""\
_gt_k = nuke.thisKnob()
_gt_n = nuke.thisNode()
_gt_kn = _gt_k.name()
if _gt_kn == "active_output":
    _gt_switch = nuke.toNode("SwitchOutput")
    if _gt_switch:
        _gt_n.begin()
        try:
            _gt_switch["which"].setValue(int(_gt_n["active_output"].getValue()))
        finally:
            _gt_n.end()
elif _gt_kn == "name":
    for _gt_name in list(_gt_n.knobs()):
        if _gt_name.startswith("{prefix}"):
            _gt_target = _gt_name[{prefix_len}:]
            if _gt_n[_gt_name].getText() and _gt_n.knob(_gt_target):
                try:
                    _gt_v = _gt_n[_gt_name].evaluate()
                except Exception:
                    _gt_v = None
                if _gt_v:
                    _gt_n[_gt_target].setValue(_gt_v)
elif not _gt_kn.startswith("_gt_") and _gt_n.knob("{prefix}" + _gt_kn):
    # Unlink: a manual edit clears the stored expression. Note the value-comparison
    # tradeoff — if the user types text identical to the current evaluated value,
    # the link is NOT cleared (values are equal). Accepted; not a bug.
    _gt_ek = _gt_n["{prefix}" + _gt_kn]
    if _gt_ek.getText():
        try:
            _gt_cur = _gt_ek.evaluate()
        except Exception:
            _gt_cur = None
        if _gt_k.getText() != _gt_cur:
            _gt_ek.setValue("")
"""


def _build_link_button_code(knob_name: str) -> str:
    """Return Python for a per-input Link button: preset chooser that writes a TCL expression into the knob."""
    return f'''\
_n = nuke.thisNode()
_p = nuke.Panel("Link {knob_name}")
_p.addEnumerationPulldown("Link to", "{{This gizmo's name}} {{Nuke script folder}} {{Nuke script name}} {{Current frame}} {{Custom node.knob}}")
if _p.show():
    _c = _p.value("Link to")
    _expr = None
    if _c == "This gizmo's name":
        _expr = "[value this.name]"
    elif _c == "Nuke script folder":
        _expr = "[file dirname [value root.name]]"
    elif _c == "Nuke script name":
        _expr = "[file rootname [file tail [value root.name]]]"
    elif _c == "Current frame":
        _expr = "[frame]"
    else:
        _t = nuke.getInput("Node.knob to link to (e.g. Text1.message)", "")
        if _t:
            _expr = "[value " + _t + "]"
    if _expr:
        _ek = _n["{GT_EXPR_PREFIX}{knob_name}"]
        _ek.setValue(_expr)
        try:
            _v = _ek.evaluate()
        except Exception:
            _v = None
        if _v:
            _n["{knob_name}"].setValue(_v)
        else:
            _ek.setValue("")
            _n["{knob_name}"].setValue(_expr)
'''


def _build_copy_link_button_code(knob_name: str) -> str:
    """Return Python for a per-output Copy Link button: clipboard copy, plus a live expression link when one node is selected."""
    return f"""\
_n = nuke.thisNode()
_expr = "[value " + _n.fullName() + ".{knob_name}]"
try:
    from PySide6.QtGui import QGuiApplication
except ImportError:
    from PySide2.QtGui import QGuiApplication
QGuiApplication.clipboard().setText(_expr)
nuke.tprint("[Griptape] Copied to clipboard: " + _expr)
_sel = [_s for _s in nuke.selectedNodes() if _s.fullName() != _n.fullName()]
if len(_sel) == 1:
    _target = _sel[0]
    _kn = nuke.getInput("Expression-link a knob on " + _target.name() + " to this output (blank = clipboard only)", "")
    if _kn:
        if _target.knob(_kn):
            _tk = _target[_kn]
            _linked = False
            try:
                _linked = bool(_tk.setExpression(_expr))
            except Exception:
                _linked = False
            if not _linked or not _tk.hasExpression():
                _tk.setValue(_expr)
                nuke.tprint("[Griptape] Set " + _target.name() + "." + _kn + " to live expression text: " + _expr)
            else:
                nuke.tprint("[Griptape] Expression-linked " + _target.name() + "." + _kn + " -> " + _expr)
        else:
            nuke.message("No knob named '" + _kn + "' on " + _target.name())
"""


class NukeGizmoBuilder:
    """Generates a Nuke .gizmo text file from a Griptape workflow shape.

    Every generated gizmo is versioned (e.g. ``my_workflow_v01``).
    """

    def __init__(
        self,
        workflow_name: str,
        workflow_shape: dict,
        companion_dir: str,
        workflow_file: str,
        available_versions: list[int] | None = None,
        current_version: int | None = None,
    ) -> None:
        self._workflow_name = workflow_name
        self._workflow_shape = workflow_shape
        self._companion_dir = companion_dir
        self._workflow_file = workflow_file
        self._available_versions: list[int] = available_versions or []
        self._current_version: int | None = current_version

    def generate(self) -> str:
        """Return the full text content of the .gizmo file."""
        input_params = self._collect_input_params()
        output_params = self._collect_output_params()
        start_node_name = self._get_start_node_name()

        media_output_names = [n for n, i in output_params.items() if i.get("type") in _MEDIA_OUTPUT_TYPES]
        media_input_names = [n for n, i in input_params.items() if i.get("type") in _MEDIA_INPUT_TYPES]
        frame_range_input_names = [n for n, i in input_params.items() if i.get("type") in _FRAME_RANGE_INPUT_TYPES]

        w = GizmoWriter()

        safe_name = _safe_knob_name(self._workflow_name)
        gizmo_node_name = versioned_node_name(safe_name, self._current_version or 1)
        w.begin_gizmo(gizmo_node_name)

        # --- Run tab (leftmost) ---
        w.add_tab("run_tab", label="Run")
        w.add_string_knob("output_dir", label="Output Directory", tooltip=_OUTPUT_DIR_TOOLTIP)
        self._write_link_button(w, "output_dir")
        w.add_text_knob("_output_dir_help", text=_OUTPUT_DIR_HELP_TEXT)
        run_code = self._build_run_button_bootstrap(
            input_params,
            list(output_params.keys()),
            start_node_name,
            media_output_names,
            media_input_names,
            frame_range_input_names,
        )
        w.add_pyscript_knob("run_workflow", label="Run Workflow", python_code=run_code)

        # Hidden companion dir knob. Left empty so the gizmo file contains no absolute paths
        # and can be shared across machines. The bootstrap resolves it at runtime via
        # nuke.pluginPath() (see _build_run_button_bootstrap).
        w.add_invisible_string_knob("_companion_dir")

        # Hidden running-state knob. Set to "1" while a workflow is executing so that
        # re-entrant button clicks can be detected and rejected.
        w.add_invisible_string_knob("_gt_running")

        # --- Inputs tab ---
        w.add_tab("inputs_tab", label="Inputs")
        for name, info in input_params.items():
            self._write_input_knob(w, name, info)

        # --- Outputs tab ---
        w.add_tab("outputs_tab", label="Outputs")
        if len(media_output_names) > 1:
            choices = [
                info.get("ui_options", {}).get("display_name") or _label(name)
                for name, info in output_params.items()
                if name in media_output_names
            ]
            w.add_enumeration_knob("active_output", "Active Output", choices)
        for name, info in output_params.items():
            self._write_output_knob(w, name, info)

        # Always present: refreshes linked fields on rename and unlinks a field
        # the user manually edits; also drives SwitchOutput for multi-output gizmos
        # (a no-op, guarded by nuke.toNode, when there is no SwitchOutput node).
        w.set_knob_changed(_build_knob_changed_code())

        w.end_gizmo_header()

        # Internal Nuke nodes for graph connectivity
        w.begin_internal_graph()
        self._write_internal_graph(w, media_input_names, media_output_names)
        w.end_group()

        validate_gizmo(w)
        return w.render()

    def _write_internal_graph(
        self,
        w: GizmoWriter,
        media_input_names: list[str],
        media_output_names: list[str],
    ) -> None:
        """Write the gizmo's internal node graph into w."""
        ypos = -100

        if media_input_names:
            for idx, _name in enumerate(media_input_names):
                w.add_input_node(_input_node_name(idx), xpos=idx * 200, ypos=ypos)
        else:
            w.add_input_node(_input_node_name(0), xpos=0, ypos=ypos)

        if len(media_output_names) > 1:
            # Write Read nodes in reverse order so that Switch input(0) maps to
            # the first media output (matching the active_output enum index 0).
            for idx, name in enumerate(reversed(media_output_names)):
                w.add_read_node(
                    _read_node_name(name),
                    xpos=idx * 200,
                    ypos=0,
                    file_expression=f"parent.{_output_knob_name(name)}",
                )
            center_x = (len(media_output_names) - 1) * 100
            w.add_switch_node(
                "SwitchOutput",
                num_inputs=len(media_output_names),
                xpos=center_x,
                ypos=100,
            )
            w.add_output_node(_output_node_name(0), xpos=center_x, ypos=200)
        elif media_output_names:
            w.add_read_node(
                _read_node_name(media_output_names[0]),
                xpos=0,
                ypos=0,
                file_expression=f"parent.{_output_knob_name(media_output_names[0])}",
            )
            w.add_output_node(_output_node_name(0), xpos=0, ypos=100)
        else:
            w.add_output_node(_output_node_name(0), xpos=0, ypos=100, no_inputs=True)

    def _get_start_node_name(self) -> str:
        inputs = self._workflow_shape.get("input", {})
        if inputs:
            return next(iter(inputs))
        return "Nuke Start Flow"

    def _collect_input_params(self) -> dict[str, dict]:
        """Return non-control input params from the workflow shape."""
        result = {}
        inputs = self._workflow_shape.get("input", {})
        for _node_name, params in inputs.items():
            for param_name, info in params.items():
                if not _is_control_param(info):
                    result[param_name] = info
        return result

    def _collect_output_params(self) -> dict[str, dict]:
        """Return non-control, non-system output params from the workflow shape."""
        result = {}
        outputs = self._workflow_shape.get("output", {})
        for _node_name, params in outputs.items():
            for param_name, info in params.items():
                if param_name in _SKIP_OUTPUT_PARAM_NAMES:
                    continue
                if _is_control_param(info):
                    continue
                result[param_name] = info
        return result

    def _write_input_knob(self, w: GizmoWriter, name: str, info: dict) -> None:
        """Write addUserKnob + default value directives for an input parameter."""
        knob_name = _safe_knob_name(name)
        label = info.get("ui_options", {}).get("display_name") or _label(name)
        param_type = info.get("type", "str")
        ui_options = info.get("ui_options", {})
        default = info.get("default_value")

        if "simple_dropdown" in ui_options:
            choices = ui_options["simple_dropdown"]
            default_index = choices.index(default) if default and default in choices else None
            w.add_enumeration_knob(knob_name, label, choices, default_index=default_index)
        elif param_type in _FILE_PATH_TYPES:
            w.add_file_knob(knob_name, label, default=_as_text(default), tooltip=_TCL_HINT_TOOLTIP)
            self._write_link_button(w, knob_name)
        elif param_type == "bool":
            w.add_bool_knob(knob_name, label, default=_as_bool(default))
        elif param_type == "float":
            w.add_double_knob(knob_name, label, default=_as_float(default))
        elif param_type == "int":
            w.add_int_knob(knob_name, label, default=_as_int(default))
        elif param_type in _MULTILINE_TYPES:
            w.add_multiline_string_knob(knob_name, label, default=_as_text(default), tooltip=_TCL_HINT_TOOLTIP)
            self._write_link_button(w, knob_name)
        else:
            w.add_string_knob(knob_name, label, default=_as_text(default), tooltip=_TCL_HINT_TOOLTIP)
            self._write_link_button(w, knob_name)

    @staticmethod
    def _write_link_button(w: GizmoWriter, knob_name: str) -> None:
        """Write a same-line Link button plus the hidden knob that stores the link's expression.

        The visible knob always displays the evaluated value; the expression
        lives in ``_gt_expr_<knob>`` and is re-evaluated by the gizmo's
        knobChanged callback (e.g. on rename).
        """
        w.add_pyscript_knob(
            f"_link_{knob_name}",
            label="Link...",
            python_code=_build_link_button_code(knob_name),
            flags="-STARTLINE",
            tooltip=_LINK_BUTTON_TOOLTIP,
        )
        w.add_invisible_string_knob(f"{GT_EXPR_PREFIX}{knob_name}")

    def _write_output_knob(self, w: GizmoWriter, name: str, info: dict) -> None:
        """Write a read-only knob for a workflow output parameter."""
        knob_name = _output_knob_name(name)
        label = info.get("ui_options", {}).get("display_name") or _label(name)
        param_type = info.get("type", "str")

        if param_type in _FILE_PATH_TYPES:
            w.add_file_knob(knob_name, label, flags="+DISABLED", tooltip=_output_tooltip(knob_name))
        elif param_type in _MULTILINE_TYPES:
            w.add_multiline_string_knob(knob_name, label, flags="+DISABLED", tooltip=_output_tooltip(knob_name))
        else:
            w.add_string_knob(knob_name, label, flags="+DISABLED", tooltip=_output_tooltip(knob_name))
        w.add_pyscript_knob(
            f"_copy_{knob_name}",
            label="Copy Link",
            python_code=_build_copy_link_button_code(knob_name),
            flags="-STARTLINE",
            tooltip=_COPY_LINK_TOOLTIP,
        )

    def _build_run_button_bootstrap(
        self,
        input_params: dict[str, dict],
        output_param_names: list[str],
        start_node_name: str,
        media_output_names: list[str],
        media_input_names: list[str],
        frame_range_input_names: list[str],
    ) -> str:
        """Build a short bootstrap that loads run_button.py from the companion dir."""
        workflow_filename = os.path.basename(self._workflow_file)
        workflow_name = self._workflow_name
        safe_name = _safe_knob_name(workflow_name)

        param_names = list(input_params.keys())
        media_input_index_map = {name: idx for idx, name in enumerate(media_input_names)}
        media_output_read_map = {name: _read_node_name(name) for name in media_output_names}
        output_knob_map = {name: _output_knob_name(name) for name in output_param_names}

        config: dict = {
            "workflow_name": workflow_name,
            "workflow_filename": workflow_filename,
            "start_node_name": start_node_name,
            "param_names": param_names,
            "media_input_names": media_input_names,
            "frame_range_input_names": frame_range_input_names,
            "media_output_names": media_output_names,
            "media_input_index_map": media_input_index_map,
            "media_output_read_map": media_output_read_map,
            "output_knob_map": output_knob_map,
            "input_node_prefix": _INPUT_NODE_PREFIX,
            "temp_file_prefix": _TEMP_FILE_PREFIX,
            "version": f"v{self._current_version}",
        }
        config_repr = repr(config)

        return f"""\
import os as _os
_node = nuke.thisNode()
_companion = _node["_companion_dir"].value()
if not _companion or not _os.path.isdir(_companion):
    for _d in nuke.pluginPath():
        _c = _os.path.join(_d, "{workflow_name}")
        if _os.path.isdir(_c) and _os.path.isfile(_os.path.join(_c, "{RUN_BUTTON_FILENAME}")):
            _companion = _c
            _node["_companion_dir"].setValue(_companion)
            break
if not _companion or not _os.path.isdir(_companion):
    nuke.message("Griptape: cannot find companion directory for '{safe_name}'. Make sure the griptape folder is on Nuke's plugin path.")
else:
    _btn_path = _os.path.join(_companion, "{RUN_BUTTON_FILENAME}")
    with open(_btn_path) as _f:
        exec(compile(_f.read(), _btn_path, "exec"), dict(globals(), **{{"__file__": _btn_path, "_config": {config_repr}}}))
"""
