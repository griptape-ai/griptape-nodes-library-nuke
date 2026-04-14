from __future__ import annotations

import os
import re

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

    The generated gizmo has:
    - One knob per user-defined input parameter (mapped from Griptape types to Nuke knob types)
    - A file picker for output directory
    - One read-only knob per user-defined output parameter (filled after workflow runs)
    - A "Run Workflow" button that loads and executes run_button.py from the companion directory
    - A hidden knob storing the companion directory path
    - One Input pipe per media input parameter for Nuke graph connectivity
    - One Output pipe per media output parameter (each backed by an internal Read node)

    When ``available_versions`` is provided (versioned publish), an enumeration knob named
    ``griptape_version`` is added at the top of the tab so users can switch between published
    versions. The run button bootstrap reads this knob to locate the correct workflow file.
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

        w.begin_gizmo(_safe_knob_name(self._workflow_name))

        # --- Griptape tab ---
        w.add_tab("griptape_tab", label=_label(self._workflow_name))

        # Version selector — only present on versioned (updated) gizmos
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
        w.add_string_knob("output_dir", label="Output Directory", default=f"{self._companion_dir}/outputs")

        # Output result knobs (read-only, filled after run)
        for name, info in output_params.items():
            self._write_output_knob(w, name, info)

        # Run button — loads run_button.py from the companion directory
        w.add_divider("_run_divider", label="")
        run_code = self._build_run_button_bootstrap(
            input_params, start_node_name, media_output_names, media_input_names
        )
        w.add_pyscript_knob("run_workflow", label="Run Workflow", python_code=run_code)

        # Hidden companion dir knob (so the button can locate run_button.py)
        w.add_invisible_string_knob("_companion_dir", value=self._companion_dir)

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
        """Write the gizmo's internal node graph into w.

        Creates one Input node per media input parameter and one Output node per
        media output parameter. Each Output is backed by its own Read node so the
        result image appears inline in Nuke's viewer.

        When there are no media inputs, a single Input is still created so the gizmo
        has at least one pipe. When there are no media outputs a single floating
        Output is created.
        """
        ypos = -100

        # --- Input nodes ---
        if media_input_names:
            for idx, _name in enumerate(media_input_names):
                w.add_input_node(_input_node_name(idx), xpos=idx * 200, ypos=ypos)
        else:
            w.add_input_node(_input_node_name(0), xpos=0, ypos=ypos)

        # --- Output nodes (one per media output, each with its own Read node) ---
        if media_output_names:
            for idx, name in enumerate(media_output_names):
                xpos = idx * 200
                w.add_read_node(_read_node_name(name), xpos=xpos, ypos=0)
                w.add_output_node(_output_node_name(idx), xpos=xpos, ypos=100)
        else:
            # No media outputs — floating Output with no Read node
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

        # Enumeration (dropdown) knob
        if "simple_dropdown" in ui_options:
            choices = ui_options["simple_dropdown"]
            default_index = choices.index(default) if default and default in choices else None
            w.add_enumeration_knob(knob_name, label, choices, default_index=default_index)

        # File path knob (images, audio, blobs)
        elif param_type in _FILE_PATH_TYPES:
            w.add_file_knob(knob_name, label, default=default or None)

        # Boolean knob
        elif param_type == "bool":
            w.add_bool_knob(knob_name, label, default=default)

        # Float knob
        elif param_type == "float":
            w.add_double_knob(knob_name, label, default=default)

        # Int knob
        elif param_type == "int":
            w.add_int_knob(knob_name, label, default=default)

        # Multi-line string knob (CSV, JSON, etc.)
        elif param_type in _MULTILINE_TYPES:
            w.add_multiline_string_knob(knob_name, label, default=default or None)

        # String knob (default for str and anything else)
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

    def _build_run_button_bootstrap(
        self,
        input_params: dict[str, dict],
        start_node_name: str,
        media_output_names: list[str],
        media_input_names: list[str],
    ) -> str:
        """Build a short bootstrap script that loads run_button.py from the companion dir.

        The full button logic lives in run_button.py (shipped alongside the workflow).
        The gizmo only needs to load it — this keeps the TCL-escaped content minimal.
        The workflow-specific values (param names, media input/output lists, etc.) are
        passed to run_button.py via a JSON config dict stored in the gizmo's knobs.
        """
        workflow_filename = os.path.basename(self._workflow_file)

        param_names = list(input_params.keys())
        media_input_index_map = {name: idx for idx, name in enumerate(media_input_names)}
        media_output_read_map = {name: _read_node_name(name) for name in media_output_names}

        # The config dict is embedded as a Python literal at publish time so that
        # run_button.py receives workflow-specific context without needing to parse
        # additional files. All values are plain Python types (str, list, dict).
        config_repr = repr(
            {
                "workflow_filename": workflow_filename,
                "start_node_name": start_node_name,
                "param_names": param_names,
                "media_input_names": media_input_names,
                "media_output_names": media_output_names,
                "media_input_index_map": media_input_index_map,
                "media_output_read_map": media_output_read_map,
                "input_node_prefix": _INPUT_NODE_PREFIX,
                "temp_file_prefix": _TEMP_FILE_PREFIX,
                "versioned": bool(self._available_versions),
            }
        )

        return f"""\
import os as _os
_companion = nuke.thisNode()["_companion_dir"].value()
_btn_path = _os.path.join(_companion, "run_button.py")
with open(_btn_path) as _f:
    exec(compile(_f.read(), _btn_path, "exec"), dict(globals(), **{{"__file__": _btn_path, "_config": {config_repr}}}))
"""
