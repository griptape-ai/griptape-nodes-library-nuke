from __future__ import annotations

import re

# Parameter types that are control-flow connections, not user data knobs
_CONTROL_PARAM_TYPES = {"parametercontroltype"}

# Output params auto-added by EndNode that we don't want as gizmo knobs
_SKIP_OUTPUT_PARAM_NAMES = {"was_successful", "result_details", "exec_in", "failed"}

# Maps Griptape parameter types to Nuke knob type IDs and Nuke knob class names
_TYPE_TO_NUKE_KNOB: dict[str, tuple[int, str]] = {
    "ImageUrlArtifact": (12, "File_Knob"),
    "ImageArtifact": (12, "File_Knob"),
    "BlobArtifact": (12, "File_Knob"),
    "str": (1, "String_Knob"),
    "float": (7, "Double_Knob"),
    "int": (3, "Int_Knob"),
    "bool": (2, "Boolean_Knob"),
}

# Image-like types that use a file browser in Nuke
_IMAGE_TYPES = {"ImageUrlArtifact", "ImageArtifact", "BlobArtifact"}


def _is_control_param(param_info: dict) -> bool:
    return param_info.get("type", "") in _CONTROL_PARAM_TYPES


def _safe_knob_name(name: str) -> str:
    """Convert a parameter name to a valid Nuke knob name (alphanumeric + underscore)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _tcl_escape(code: str) -> str:
    """Escape a Python code string for embedding inside a TCL double-quoted string.

    In Nuke's gizmo format, the T value of a PyScript_Knob is a TCL double-quoted
    string where: \\ -> literal backslash, \" -> literal quote, \n -> newline.
    """
    code = code.replace("\\", "\\\\")
    code = code.replace('"', '\\"')
    code = code.replace("\n", "\\n")
    return code


def _label(name: str) -> str:
    """Convert a snake_case name to a human-readable label."""
    return name.replace("_", " ").title()


class NukeGizmoBuilder:
    """Generates a Nuke .gizmo text file from a Griptape workflow shape.

    The generated gizmo has:
    - One knob per user-defined input parameter (mapped from Griptape types to Nuke knob types)
    - A file picker for output directory
    - One read-only knob per user-defined output parameter (filled after workflow runs)
    - A "Run Workflow" button that invokes nuke_workflow_runner.py via subprocess
    - A hidden knob storing the companion directory path
    - Input and Output pipe nodes for Nuke graph connectivity
    """

    def __init__(
        self,
        workflow_name: str,
        workflow_shape: dict,
        companion_dir: str,
        workflow_file: str,
    ) -> None:
        self._workflow_name = workflow_name
        self._workflow_shape = workflow_shape
        self._companion_dir = companion_dir
        self._workflow_file = workflow_file

    def generate(self) -> str:
        """Return the full text content of the .gizmo file."""
        input_params = self._collect_input_params()
        output_params = self._collect_output_params()
        start_node_name = self._get_start_node_name()

        lines: list[str] = []
        lines.append("Gizmo {")
        lines.append(f" name {_safe_knob_name(self._workflow_name)}")
        lines.append(" tile_color 0xff9900ff")
        lines.append("")

        # --- Griptape tab ---
        lines.append(' addUserKnob {20 griptape_tab l "Griptape Workflow"}')

        # Input knobs
        if input_params:
            lines.append(' addUserKnob {26 _inputs_divider l "Inputs" +STARTLINE}')
        for name, info in input_params.items():
            lines.extend(self._input_knob_lines(name, info))

        # Output directory picker
        lines.append(' addUserKnob {26 _output_divider l "Outputs" +STARTLINE}')
        lines.append(' addUserKnob {1 output_dir l "Output Directory"}')
        lines.append(f' output_dir "{self._companion_dir}"')

        # Output result knobs (read-only, filled after run)
        for name, info in output_params.items():
            lines.extend(self._output_knob_lines(name, info))

        # Run button
        lines.append(' addUserKnob {26 _run_divider l "" +STARTLINE}')
        run_code = self._build_run_button_code(input_params, start_node_name)
        escaped_code = _tcl_escape(run_code)
        lines.append(f' addUserKnob {{22 run_workflow l "Run Workflow" T "{escaped_code}" +STARTLINE}}')

        # Hidden companion dir knob (so the button can locate the runner)
        lines.append(' addUserKnob {1 _companion_dir l "" +INVISIBLE}')
        lines.append(f' _companion_dir {self._companion_dir}')

        lines.append("}")

        # Internal Nuke nodes for graph connectivity
        lines.append(" Input {")
        lines.append("  inputs 0")
        lines.append("  name Input1")
        lines.append("  xpos 0")
        lines.append("  ypos -100")
        lines.append(" }")
        lines.append(" Output {")
        lines.append("  inputs 0")
        lines.append("  name Output1")
        lines.append("  xpos 0")
        lines.append("  ypos 100")
        lines.append(" }")
        lines.append("end_group")

        return "\n".join(lines) + "\n"

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

    def _input_knob_lines(self, name: str, info: dict) -> list[str]:
        """Generate addUserKnob + default value lines for an input parameter."""
        knob_name = _safe_knob_name(name)
        label = info.get("ui_options", {}).get("display_name") or _label(name)
        param_type = info.get("type", "str")
        ui_options = info.get("ui_options", {})
        default = info.get("default_value")

        lines: list[str] = []

        # Enumeration (dropdown) knob
        if "simple_dropdown" in ui_options:
            choices = ui_options["simple_dropdown"]
            choices_str = " ".join(f'"{c}"' if " " in str(c) else str(c) for c in choices)
            lines.append(f' addUserKnob {{4 {knob_name} l "{label}" M {{{choices_str}}}}}')
            if default and default in choices:
                idx = choices.index(default)
                lines.append(f" {knob_name} {idx}")

        # Image / file path knob
        elif param_type in _IMAGE_TYPES:
            lines.append(f' addUserKnob {{12 {knob_name} l "{label}"}}')
            if default:
                lines.append(f' {knob_name} "{default}"')

        # Boolean knob
        elif param_type == "bool":
            lines.append(f' addUserKnob {{2 {knob_name} l "{label}"}}')
            if default is not None:
                lines.append(f" {knob_name} {'1' if default else '0'}")

        # Float knob
        elif param_type == "float":
            lines.append(f' addUserKnob {{7 {knob_name} l "{label}"}}')
            if default is not None:
                lines.append(f" {knob_name} {default}")

        # Int knob
        elif param_type == "int":
            lines.append(f' addUserKnob {{3 {knob_name} l "{label}"}}')
            if default is not None:
                lines.append(f" {knob_name} {default}")

        # String knob (default for str and anything else)
        else:
            lines.append(f' addUserKnob {{1 {knob_name} l "{label}"}}')
            if default:
                lines.append(f' {knob_name} "{default}"')

        return lines

    def _output_knob_lines(self, name: str, info: dict) -> list[str]:
        """Generate a read-only knob for a workflow output parameter."""
        knob_name = _safe_knob_name(name)
        label = info.get("ui_options", {}).get("display_name") or _label(name)
        param_type = info.get("type", "str")

        if param_type in _IMAGE_TYPES:
            return [f' addUserKnob {{12 {knob_name} l "{label}" +DISABLED}}']
        return [f' addUserKnob {{1 {knob_name} l "{label}" +DISABLED}}']

    def _build_run_button_code(self, input_params: dict[str, dict], start_node_name: str) -> str:
        """Build the Python code that runs when the user clicks 'Run Workflow'."""
        # Build the list of input param names to collect from knobs
        param_names = list(input_params.keys())
        param_names_repr = repr(param_names)

        # The workflow file name (just the filename, in the companion dir)
        import os
        workflow_filename = os.path.basename(self._workflow_file)

        # Use the pre-built .venv inside the companion dir. This venv is created
        # at publish time via "uv sync", so no runtime dependency on uv or any
        # external Python tooling. The folder is fully self-contained and shareable.
        code = f"""\
import subprocess, json, os, platform
node = nuke.thisNode()
companion = node["_companion_dir"].value()
workflow_file = os.path.join(companion, {workflow_filename!r})
runner = os.path.join(companion, "run_workflow.py")
inputs = {{}}
for _k in {param_names_repr}:
    if node.knob(_k):
        inputs[_k] = node[_k].value()
output_dir = node["output_dir"].value() or companion
flow_input = json.dumps({{{start_node_name!r}: inputs}})
if platform.system() == "Windows":
    venv_python = os.path.join(companion, ".venv", "Scripts", "python.exe")
else:
    venv_python = os.path.join(companion, ".venv", "bin", "python")
if not os.path.isfile(venv_python):
    nuke.message("Error: .venv not found in companion directory.\\nRe-publish the gizmo to rebuild it, or run 'uv sync --project ' + companion + ' in a terminal.")
else:
    cmd = [venv_python, runner, "--workflow-file", workflow_file, "--json-input", flow_input, "--output-dir", output_dir]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=companion, timeout=600)
    if result.returncode == 0:
        try:
            output = json.loads(result.stdout.strip())
            for _k, _v in output.items():
                if node.knob(_k):
                    node[_k].setValue(str(_v))
            nuke.message("Workflow completed!")
        except Exception as _e:
            nuke.message("Error parsing output: " + str(_e) + "\\n" + result.stdout[:300])
    else:
        nuke.message("Workflow failed:\\n" + result.stderr[:500])\
"""
        return code
