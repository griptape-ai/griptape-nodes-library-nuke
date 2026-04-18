from __future__ import annotations

import os
import re

from publish_gizmo.constants import RUN_BUTTON_FILENAME, versioned_node_name
from publish_gizmo.gizmo_validator import validate_gizmo_text
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
    "TextArtifact": (NukeKnobType.MULTILINE_STRING, "String_Knob"),
    "str": (NukeKnobType.MULTILINE_STRING, "String_Knob"),
    "float": (NukeKnobType.DOUBLE, "Double_Knob"),
    "int": (NukeKnobType.INT, "Int_Knob"),
    "bool": (NukeKnobType.BOOL, "Bool_Knob"),
    "CsvArtifact": (NukeKnobType.MULTILINE_STRING, "MultiLine_String_Knob"),
    "JsonArtifact": (NukeKnobType.MULTILINE_STRING, "MultiLine_String_Knob"),
}

# File-path types that use a file browser in Nuke
_FILE_PATH_TYPES = {"ImageUrlArtifact", "ImageArtifact", "BlobArtifact", "AudioArtifact"}

# Types that use a multi-line text field in Nuke
_MULTILINE_TYPES = {"CsvArtifact", "JsonArtifact"}

# Media types whose outputs should be displayed in an internal Read node in Nuke
_MEDIA_OUTPUT_TYPES = {"ImageUrlArtifact", "ImageArtifact", "BlobArtifact", "AudioArtifact"}

# Media input types that support upstream Nuke node connections (render-to-temp)
_MEDIA_INPUT_TYPES = {"ImageUrlArtifact", "ImageArtifact", "BlobArtifact", "AudioArtifact"}

# Naming conventions for internal Nuke nodes inside the gizmo
_READ_NODE_PREFIX = "GEN_READ"
_INPUT_NODE_PREFIX = "Input"
_OUTPUT_NODE_PREFIX = "Output"
_TEMP_FILE_PREFIX = "gt_input"


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


def _build_active_output_knob_changed() -> str:
    """Return Python code for the gizmo's knobChanged callback.

    When the user changes the ``active_output`` selector, this code updates
    the internal SwitchOutput node's ``which`` knob so the correct Read node
    flows to the gizmo's output pipe immediately — no re-run needed.
    """
    return """\
if nuke.thisKnob().name() == "active_output":
    n = nuke.thisNode()
    n.begin()
    try:
        switch = nuke.toNode("SwitchOutput")
        if switch:
            switch["which"].setValue(int(n["active_output"].getValue()))
    finally:
        n.end()
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

        w = GizmoWriter()

        safe_name = _safe_knob_name(self._workflow_name)
        gizmo_node_name = versioned_node_name(safe_name, self._current_version or 1)
        w.begin_gizmo(gizmo_node_name)

        # --- Run tab (leftmost) ---
        w.add_tab("run_tab", label="Run")
        w.add_string_knob("output_dir", label="Output Directory")
        run_code = self._build_run_button_bootstrap(
            input_params, list(output_params.keys()), start_node_name, media_output_names, media_input_names
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
            choices = [info.get("ui_options", {}).get("display_name") or _label(name) for name, info in output_params.items() if name in media_output_names]
            w.add_enumeration_knob("active_output", "Active Output", choices)
            w.set_knob_changed(_build_active_output_knob_changed())
        for name, info in output_params.items():
            self._write_output_knob(w, name, info)

        w.end_gizmo_header()

        # Internal Nuke nodes for graph connectivity
        w.begin_internal_graph()
        self._write_internal_graph(w, media_input_names, media_output_names)
        w.end_group()

        gizmo_text = w.render()
        validate_gizmo_text(gizmo_text)
        return gizmo_text

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
                w.add_read_node(_read_node_name(name), xpos=idx * 200, ypos=0)
            center_x = (len(media_output_names) - 1) * 100
            w.add_switch_node(
                "SwitchOutput",
                num_inputs=len(media_output_names),
                xpos=center_x,
                ypos=100,
            )
            w.add_output_node(_output_node_name(0), xpos=center_x, ypos=200)
        elif media_output_names:
            w.add_read_node(_read_node_name(media_output_names[0]), xpos=0, ypos=0)
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
            w.add_file_knob(knob_name, label, default=default or None)
        elif param_type == "bool":
            w.add_bool_knob(knob_name, label, default=default)
        elif param_type == "float":
            w.add_double_knob(knob_name, label, default=default)
        elif param_type == "int":
            w.add_int_knob(knob_name, label, default=default)
        elif param_type in _MULTILINE_TYPES:
            w.add_multiline_string_knob(knob_name, label, default=default or None)
        else:
            w.add_string_knob(knob_name, label, default=default or None)

    def _write_output_knob(self, w: GizmoWriter, name: str, info: dict) -> None:
        """Write a read-only knob for a workflow output parameter."""
        knob_name = _output_knob_name(name)
        label = info.get("ui_options", {}).get("display_name") or _label(name)
        param_type = info.get("type", "str")

        if param_type in _FILE_PATH_TYPES:
            w.add_file_knob(knob_name, label, flags="+DISABLED")
        elif param_type in _MULTILINE_TYPES:
            w.add_multiline_string_knob(knob_name, label, flags="+DISABLED")
        else:
            w.add_string_knob(knob_name, label, flags="+DISABLED")

    def _build_run_button_bootstrap(
        self,
        input_params: dict[str, dict],
        output_param_names: list[str],
        start_node_name: str,
        media_output_names: list[str],
        media_input_names: list[str],
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
