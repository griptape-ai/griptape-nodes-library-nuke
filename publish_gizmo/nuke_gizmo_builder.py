from __future__ import annotations

import os
import re

from publish_gizmo.constants import RUN_BUTTON_FILENAME, versioned_gizmo_glob, versioned_node_name
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


def _label(name: str) -> str:
    """Convert a snake_case name to a human-readable label."""
    return name.replace("_", " ").title()


class NukeGizmoBuilder:
    """Generates a Nuke .gizmo text file from a Griptape workflow shape.

    Every generated gizmo is versioned (e.g. ``my_workflow_v01``). When
    ``available_versions`` is provided, a ``griptape_version`` enumeration knob
    and a ``knobChanged`` swap callback are added so artists can switch between
    published versions without leaving the properties panel.
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

        if self._available_versions:
            w.set_knob_changed(self._build_knob_changed_code())

        # --- Griptape tab ---
        w.add_tab("griptape_tab", label=_label(self._workflow_name))

        if self._available_versions:
            version_choices = [f"v{v}" for v in self._available_versions]
            default_idx = None
            if self._current_version is not None:
                current_label = f"v{self._current_version}"
                if current_label in version_choices:
                    default_idx = version_choices.index(current_label)
            w.add_enumeration_knob("griptape_version", "Version", version_choices, default_index=default_idx)

        # Input knobs
        if input_params:
            w.add_divider("_inputs_divider", label="Inputs")
        for name, info in input_params.items():
            self._write_input_knob(w, name, info)

        # Output directory picker
        w.add_divider("_output_divider", label="Outputs")
        w.add_string_knob("output_dir", label="Output Directory")

        # Output result knobs (read-only, filled after run)
        for name, info in output_params.items():
            self._write_output_knob(w, name, info)

        # Run button — loads run_button.py from the companion directory
        w.add_divider("_run_divider", label="")
        run_code = self._build_run_button_bootstrap(
            input_params, start_node_name, media_output_names, media_input_names
        )
        w.add_pyscript_knob("run_workflow", label="Run Workflow", python_code=run_code)

        # Hidden companion dir knob. Left empty so the gizmo file contains no absolute paths
        # and can be shared across machines. The bootstrap resolves it at runtime via
        # nuke.pluginPath() (see _build_run_button_bootstrap).
        w.add_invisible_string_knob("_companion_dir")

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

        if media_output_names:
            for idx, name in enumerate(media_output_names):
                xpos = idx * 200
                w.add_read_node(_read_node_name(name), xpos=xpos, ypos=0)
                w.add_output_node(_output_node_name(idx), xpos=xpos, ypos=100)
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
        knob_name = _safe_knob_name(name)
        label = info.get("ui_options", {}).get("display_name") or _label(name)
        param_type = info.get("type", "str")

        if param_type in _FILE_PATH_TYPES:
            w.add_file_knob(knob_name, label, flags="+DISABLED")
        elif param_type in _MULTILINE_TYPES:
            w.add_multiline_string_knob(knob_name, label, flags="+DISABLED")
        else:
            w.add_string_knob(knob_name, label, flags="+DISABLED")

    def _build_knob_changed_code(self) -> str:
        """Build the knobChanged callback embedded in the gizmo.

        Handles two events:
        - ``showPanel``: resolves the companion dir and refreshes the version
          dropdown from ``nuke.plugins()`` so newly published versions appear
          without re-publishing.
        - ``griptape_version``: swaps the current node for the selected version's
          gizmo (LiveGroup-style), transferring all connections and knob values.
        """
        workflow_name = self._workflow_name
        safe_name = _safe_knob_name(workflow_name)
        version_glob = versioned_gizmo_glob(safe_name)
        return f"""\
import os as _os, re as _re
_k = nuke.thisKnob()
_node = nuke.thisNode()

def _resolve_companion(_node):
    _companion = _node["_companion_dir"].value()
    if not _companion or not _os.path.isdir(_companion):
        for _d in nuke.pluginPath():
            _c = _os.path.join(_d, "{workflow_name}")
            if _os.path.isdir(_c) and _os.path.isfile(_os.path.join(_c, "{RUN_BUTTON_FILENAME}")):
                _companion = _c
                _node["_companion_dir"].setValue(_companion)
                break
    return _companion

if _k and _k.name() == "showPanel":
    _companion = _resolve_companion(_node)
    if _companion and _os.path.isdir(_companion):
        _found = nuke.plugins(nuke.ALL, "{version_glob}")
        _nums = []
        for _p in _found:
            _m = _re.search(r"_v(\\d+)\\.gizmo$", _os.path.basename(_p))
            if _m:
                _nums.append(int(_m.group(1)))
        if _nums:
            _choices = ["v" + str(n) for n in sorted(_nums)]
            _vk = _node.knob("griptape_version")
            if _vk:
                _cur = _vk.value()
                _vk.setValues(_choices)
                if _cur in _choices:
                    _vk.setValue(_cur)

elif _k and _k.name() == "griptape_version":
    _new_ver = _node["griptape_version"].value()  # e.g. "v2"
    _padded = _new_ver[1:].zfill(2)
    _target = "{safe_name}_v" + _padded
    if _node.Class() != _target:
        _name = _node.name()
        _xpos = _node.xpos()
        _ypos = _node.ypos()
        _companion = _resolve_companion(_node)
        _output_dir = _node["output_dir"].value() if _node.knob("output_dir") else ""
        _upstream = {{}}
        for _i in range(_node.inputs()):
            _inp = _node.input(_i)
            if _inp:
                _upstream[_i] = _inp.name()
        _downstream = []
        for _n in nuke.allNodes():
            if _n == _node:
                continue
            for _i in range(_n.inputs()):
                if _n.input(_i) == _node:
                    _downstream.append((_n.name(), _i))
        _skip = {{"griptape_version", "run_workflow", "tile_color", "label", "xpos", "ypos", "name"}}
        _vals = {{}}
        for _kn in _node.allKnobs():
            _kn_name = _kn.name()
            if _kn_name and not _kn_name.startswith("_") and _kn_name not in _skip:
                try:
                    _vals[_kn_name] = _kn.value()
                except Exception:
                    pass
        # Free the name before creating the replacement so there is no conflict
        _node.setName("__gt_swap_pending__")
        _new = nuke.createNode(_target, inpanel=False)
        _new.setName(_name)
        _new.setXpos(_xpos)
        _new.setYpos(_ypos)
        if _companion and _new.knob("_companion_dir"):
            _new["_companion_dir"].setValue(_companion)
        if _output_dir and _new.knob("output_dir"):
            _new["output_dir"].setValue(_output_dir)
        if _new.knob("griptape_version"):
            _new["griptape_version"].setValue(_new_ver)
        for _kn_name, _val in _vals.items():
            if _new.knob(_kn_name):
                try:
                    _new[_kn_name].setValue(_val)
                except Exception:
                    pass
        for _i, _inp_name in _upstream.items():
            _inp = nuke.toNode(_inp_name)
            if _inp:
                _new.setInput(_i, _inp)
        for _dep_name, _dep_i in _downstream:
            _dep = nuke.toNode(_dep_name)
            if _dep:
                _dep.setInput(_dep_i, _new)
        nuke.show(_new)
        # Defer deletion — destroying thisNode() inside its own knobChanged is unsafe
        nuke.executeDeferred(lambda _n=_node: nuke.delete(_n))
"""

    def _build_run_button_bootstrap(
        self,
        input_params: dict[str, dict],
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

        config: dict = {
            "workflow_name": workflow_name,
            "workflow_filename": workflow_filename,
            "start_node_name": start_node_name,
            "param_names": param_names,
            "media_input_names": media_input_names,
            "media_output_names": media_output_names,
            "media_input_index_map": media_input_index_map,
            "media_output_read_map": media_output_read_map,
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
