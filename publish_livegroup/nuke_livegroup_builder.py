"""Generates Nuke LiveGroup .nk file content and knob specs from a Griptape workflow shape.

The .nk file defines ONLY the internal graph nodes (Input, Read, Output).
User-facing knobs are described as a serializable list of knob spec dicts and stored
in griptape_livegroups.json. When a LiveGroup is created via griptape_livegroups.py,
these knobs are added to the LiveGroup container node via the Nuke Python API
(node.addKnob()), so run_button.py works unchanged — nuke.thisNode()["knob_name"]
reads directly from the LiveGroup node.
"""

from __future__ import annotations

import os
import re

from publish_livegroup.nk_writer import NkWriter

# Parameter types that are control-flow connections, not user data knobs
_CONTROL_PARAM_TYPES = {"parametercontroltype"}

# Output params auto-added by EndNode that we don't want as LiveGroup knobs
_SKIP_OUTPUT_PARAM_NAMES = {"was_successful", "result_details", "exec_in", "failed"}

_FILE_PATH_TYPES = {"ImageUrlArtifact", "ImageArtifact", "BlobArtifact", "AudioArtifact"}
_MULTILINE_TYPES = {"CsvArtifact", "JsonArtifact"}
_MEDIA_OUTPUT_TYPES = {"ImageUrlArtifact", "ImageArtifact", "BlobArtifact", "AudioArtifact"}
_MEDIA_INPUT_TYPES = {"ImageUrlArtifact", "ImageArtifact", "BlobArtifact", "AudioArtifact"}

_READ_NODE_PREFIX = "GEN_READ"
_INPUT_NODE_PREFIX = "Input"
_OUTPUT_NODE_PREFIX = "Output"
_TEMP_FILE_PREFIX = "gt_input"


def _read_node_name(param_name: str) -> str:
    return f"{_READ_NODE_PREFIX}_{_safe_knob_name(param_name)}"


def _input_node_name(index: int) -> str:
    return f"{_INPUT_NODE_PREFIX}{index + 1}"


def _output_node_name(index: int) -> str:
    return f"{_OUTPUT_NODE_PREFIX}{index + 1}"


def _is_control_param(param_info: dict) -> bool:
    return param_info.get("type", "") in _CONTROL_PARAM_TYPES


def _safe_knob_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _label(name: str) -> str:
    return name.replace("_", " ").title()


class NukeLiveGroupBuilder:
    """Builds the .nk file and knob spec for a Griptape LiveGroup.

    generate()      — returns the .nk file content (internal graph nodes only).
    get_knob_spec() — returns a JSON-serializable list of knob descriptors that
                      griptape_livegroups.py uses to call node.addKnob() when the
                      LiveGroup is created in Nuke.
    """

    def __init__(
        self,
        workflow_name: str,
        workflow_shape: dict,
        companion_dir: str,
        workflow_file: str,
        version: int = 1,
    ) -> None:
        self._workflow_name = workflow_name
        self._workflow_shape = workflow_shape
        self._companion_dir = companion_dir
        self._workflow_file = workflow_file
        self._version = version

    def generate(self) -> str:
        """Return the .nk file content — internal graph nodes only, no knob directives."""
        input_params = self._collect_input_params()
        output_params = self._collect_output_params()

        media_output_names = [n for n, i in output_params.items() if i.get("type") in _MEDIA_OUTPUT_TYPES]
        media_input_names = [n for n, i in input_params.items() if i.get("type") in _MEDIA_INPUT_TYPES]

        w = NkWriter()
        self._write_internal_graph(w, media_input_names, media_output_names)
        return w.render()

    def get_knob_spec(self) -> list[dict]:
        """Return a JSON-serializable list of knob descriptors for this workflow.

        Each descriptor has at minimum a "type" key. griptape_livegroups.py
        iterates these and calls the corresponding nuke.Knob subclass constructor
        to add each knob to the LiveGroup container node.
        """
        input_params = self._collect_input_params()
        output_params = self._collect_output_params()
        start_node_name = self._get_start_node_name()

        media_output_names = [n for n, i in output_params.items() if i.get("type") in _MEDIA_OUTPUT_TYPES]
        media_input_names = [n for n, i in input_params.items() if i.get("type") in _MEDIA_INPUT_TYPES]

        specs: list[dict] = []

        # Tab
        specs.append({"type": "tab", "name": "griptape_tab", "label": _label(self._workflow_name)})

        # Input knobs
        if input_params:
            specs.append({"type": "divider", "name": "_inputs_divider", "label": "Inputs"})
        for name, info in input_params.items():
            specs.append(self._input_knob_spec(name, info))

        # Output dir + result knobs
        specs.append({"type": "divider", "name": "_output_divider", "label": "Outputs"})
        specs.append({
            "type": "string",
            "name": "output_dir",
            "label": "Output Directory",
            "default": f"{self._companion_dir}/outputs",
        })
        for name, info in output_params.items():
            specs.append(self._output_knob_spec(name, info))

        # Run button
        specs.append({"type": "divider", "name": "_run_divider", "label": ""})
        run_code = self._build_run_button_bootstrap(
            input_params, start_node_name, media_output_names, media_input_names
        )
        specs.append({"type": "pyscript", "name": "run_workflow", "label": "Run Workflow", "code": run_code})

        # Hidden companion dir
        specs.append({"type": "invisible_string", "name": "_companion_dir", "value": self._companion_dir})

        return specs

    # -- Internal graph --

    def _write_internal_graph(
        self,
        w: NkWriter,
        media_input_names: list[str],
        media_output_names: list[str],
    ) -> None:
        if media_input_names:
            for idx, _name in enumerate(media_input_names):
                w.add_input_node(_input_node_name(idx), xpos=idx * 200, ypos=-100)
        else:
            w.add_input_node(_input_node_name(0), xpos=0, ypos=-100)

        if media_output_names:
            for idx, name in enumerate(media_output_names):
                xpos = idx * 200
                w.add_read_node(_read_node_name(name), xpos=xpos, ypos=0)
                w.add_output_node(_output_node_name(idx), xpos=xpos, ypos=100)
        else:
            w.add_output_node(_output_node_name(0), xpos=0, ypos=100, no_inputs=True)

    # -- Knob spec helpers --

    def _input_knob_spec(self, name: str, info: dict) -> dict:
        knob_name = _safe_knob_name(name)
        label = info.get("ui_options", {}).get("display_name") or _label(name)
        param_type = info.get("type", "str")
        ui_options = info.get("ui_options", {})
        default = info.get("default_value")

        if "simple_dropdown" in ui_options:
            choices = ui_options["simple_dropdown"]
            default_index = choices.index(default) if default and default in choices else None
            return {"type": "enumeration", "name": knob_name, "label": label,
                    "choices": choices, "default_index": default_index}
        if param_type in _FILE_PATH_TYPES:
            return {"type": "file", "name": knob_name, "label": label, "default": default or ""}
        if param_type == "bool":
            return {"type": "bool", "name": knob_name, "label": label, "default": bool(default)}
        if param_type == "float":
            return {"type": "double", "name": knob_name, "label": label, "default": default}
        if param_type == "int":
            return {"type": "int", "name": knob_name, "label": label, "default": default}
        if param_type in _MULTILINE_TYPES:
            return {"type": "multiline_string", "name": knob_name, "label": label, "default": default or ""}
        return {"type": "string", "name": knob_name, "label": label, "default": default or ""}

    def _output_knob_spec(self, name: str, info: dict) -> dict:
        knob_name = _safe_knob_name(name)
        label = info.get("ui_options", {}).get("display_name") or _label(name)
        param_type = info.get("type", "str")

        if param_type in _FILE_PATH_TYPES:
            return {"type": "file", "name": knob_name, "label": label, "disabled": True}
        if param_type in _MULTILINE_TYPES:
            return {"type": "multiline_string", "name": knob_name, "label": label, "disabled": True}
        return {"type": "string", "name": knob_name, "label": label, "disabled": True}

    # -- Shared helpers --

    def _get_start_node_name(self) -> str:
        inputs = self._workflow_shape.get("input", {})
        if inputs:
            return next(iter(inputs))
        return "Nuke Start Flow"

    def _collect_input_params(self) -> dict[str, dict]:
        result = {}
        inputs = self._workflow_shape.get("input", {})
        for _node_name, params in inputs.items():
            for param_name, info in params.items():
                if not _is_control_param(info):
                    result[param_name] = info
        return result

    def _collect_output_params(self) -> dict[str, dict]:
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

    def _build_run_button_bootstrap(
        self,
        input_params: dict[str, dict],
        start_node_name: str,
        media_output_names: list[str],
        media_input_names: list[str],
    ) -> str:
        workflow_filename = os.path.basename(self._workflow_file)
        param_names = list(input_params.keys())
        media_input_index_map = {name: idx for idx, name in enumerate(media_input_names)}
        media_output_read_map = {name: _read_node_name(name) for name in media_output_names}

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
            }
        )

        return (
            'import os as _os\n'
            '_companion = nuke.thisNode()["_companion_dir"].value()\n'
            '_btn_path = _os.path.join(_companion, "run_button.py")\n'
            'with open(_btn_path) as _f:\n'
            f'    exec(compile(_f.read(), _btn_path, "exec"), dict(globals(), **{{"__file__": _btn_path, "_config": {config_repr}}}))\n'
        )
