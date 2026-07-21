from __future__ import annotations

import atexit
import json
import logging
import os
import pathlib
import shutil
import subprocess
import tempfile
import urllib.request
import uuid
from typing import Any

from griptape_nodes.common.macro_parser import ParsedMacro
from griptape_nodes.common.macro_parser.exceptions import MacroSyntaxError
from griptape_nodes.exe_types.core_types import NodeMessageResult, Parameter, ParameterGroup
from griptape_nodes.exe_types.node_types import SuccessFailureNode
from griptape_nodes.exe_types.param_types.parameter_button import ParameterButton
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString
from griptape_nodes.files.file import File
from griptape_nodes.files.project_file import ProjectFileDestination
from griptape_nodes.retained_mode.events.os_events import (
    DeleteFileRequest,
    WriteFileRequest,
    WriteFileResultSuccess,
)
from griptape_nodes.retained_mode.events.project_events import GetPathForMacroRequest, GetPathForMacroResultSuccess
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.traits.button import Button, ButtonDetailsMessagePayload
from griptape_nodes.traits.file_system_picker import FileSystemPicker
from griptape_nodes.traits.options import Options
from griptape_nodes.traits.slider import Slider

from execution.direct import DirectSubprocessProvider
from execution.installations import NukeInstallation, find_installation, merged_installations
from nuke_plugin.installer import get_plugin_path
from nuke_runner.manifest import JobManifest, KnobOverride, ManifestInput, ManifestOutput
from script_parser.annotation import ExposedKnob, GriptapeAnnotation
from script_parser.knob_type_map import griptape_type_for_knob, resolve_exposed_knob_type
from script_parser.parser import ParsedNode, parse_script
from script_parser.sidecar import read_knob_schema, read_sidecar

_RUNNER_SCRIPT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "nuke_runner", "runner.py"))
_BAKE_RUNNER_SCRIPT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "nuke_runner", "baker.py"))

_TEMP_SUFFIX: dict[str, str] = {
    "ThreeDUrlArtifact": ".obj",
    "GLTFUrlArtifact": ".glb",
    "VideoUrlArtifact": ".mp4",
}


def _path_to_artifact(gt_type: str, path: str) -> Any:
    """Convert a runner output file path to the appropriate Griptape artifact."""
    if gt_type in {"ThreeDUrlArtifact", "GLTFUrlArtifact"}:
        if not isinstance(path, str):
            raise TypeError(f"Expected str path for {gt_type!r}, got {type(path).__name__!r}: {path!r}")
        suffix = pathlib.Path(path).suffix.lower() or ".obj"
        if suffix in {".glb", ".gltf"}:
            file_bytes = File(path).read_bytes()
            serve_suffix = suffix
        else:
            try:
                import trimesh  # pyright: ignore[reportMissingImports]  # noqa: PLC0415

                scene = trimesh.load(path)
                file_bytes = scene.export(file_type="glb")  # pyright: ignore[reportAttributeAccessIssue,reportCallIssue]
                serve_suffix = ".glb"
            except Exception:
                file_bytes = File(path).read_bytes()
                serve_suffix = suffix
        saved = ProjectFileDestination.from_situation(
            filename=f"model{serve_suffix}", situation="save_node_output"
        ).write_bytes(file_bytes)
        try:
            from griptape_nodes_library.three_d.three_d_artifact import (  # pyright: ignore[reportMissingImports]
                ThreeDUrlArtifact,  # noqa: PLC0415
            )
        except ImportError:
            return saved.location
        return ThreeDUrlArtifact(value=saved.location)
    if gt_type == "VideoUrlArtifact":
        if not isinstance(path, str):
            raise TypeError(f"Expected str path for {gt_type!r}, got {type(path).__name__!r}: {path!r}")
        file_bytes = File(path).read_bytes()
        suffix = pathlib.Path(path).suffix or ".mp4"
        saved = ProjectFileDestination.from_situation(
            filename=f"video{suffix}", situation="save_node_output"
        ).write_bytes(file_bytes)
        try:
            from griptape.artifacts import VideoUrlArtifact  # noqa: PLC0415

            return VideoUrlArtifact(value=saved.location)
        except ImportError:
            return saved.location
    if not isinstance(path, str):
        raise TypeError(f"Expected str path for {gt_type!r}, got {type(path).__name__!r}: {path!r}")
    file_bytes = File(path).read_bytes()
    suffix = pathlib.Path(path).suffix or ".png"
    saved = ProjectFileDestination.from_situation(filename=f"image{suffix}", situation="save_node_output").write_bytes(
        file_bytes
    )
    try:
        from griptape.artifacts import ImageUrlArtifact  # noqa: PLC0415

        return ImageUrlArtifact(value=saved.location)
    except ImportError:
        return saved.location


def _coerce_knob_value(v: Any) -> float | int | str:
    """Coerce a parameter value to a type Nuke's knob.setValue() accepts."""
    if isinstance(v, bool):
        return int(v)  # Bool_Knob.setValue(0/1) is reliable; str("True") is not
    s = str(v)
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


# Startup script run inside Nuke GUI via `nuke -p`. Opens the .nk file and applies
# knob overrides before the artist sees the session.
_OPEN_IN_NUKE_STARTUP_TEMPLATE = """\
import json
import sys
import nuke

nuke.scriptOpen({script_path})
try:
    with open({manifest_path}, encoding="utf-8") as f:
        data = json.load(f)
except Exception as exc:
    print("Griptape open-in-nuke: could not load overrides: " + str(exc), file=sys.stderr)
    data = {{}}
for o in data.get("knob_overrides", []):
    node = nuke.toNode(o["node"])
    if node is None:
        print("Griptape open-in-nuke: node " + repr(o["node"]) + " not found", file=sys.stderr)
        continue
    try:
        node[o["knob"]].setValue(o["value"])
    except Exception as exc:
        print("Griptape open-in-nuke: " + o["node"] + "." + o["knob"] + ": " + str(exc), file=sys.stderr)
"""


def _build_open_in_nuke_launch(
    nuke_exe: str,
    script_path: str,
    overrides: list[KnobOverride],
    env: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    """Return (command, env) for launching Nuke in GUI mode with overrides pre-applied."""
    overrides_data = {"knob_overrides": [{"node": o.node, "knob": o.knob, "value": o.value} for o in overrides]}
    tmpdir = tempfile.mkdtemp(prefix="griptape_nuke_")
    atexit.register(shutil.rmtree, tmpdir, True)

    manifest_path = os.path.join(tmpdir, "overrides.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(overrides_data, f)

    startup_src = _OPEN_IN_NUKE_STARTUP_TEMPLATE.format(
        script_path=repr(script_path.replace("\\", "/")),
        manifest_path=repr(manifest_path.replace("\\", "/")),
    )
    startup_path = os.path.join(tmpdir, "startup.py")
    with open(startup_path, "w", encoding="utf-8") as f:
        f.write(startup_src)

    cmd = [nuke_exe, "-p", startup_path]
    return cmd, env


class NukeScriptNode(SuccessFailureNode):
    """Runs a .nk script headlessly and surfaces annotated nodes as typed ports."""

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)
        self._dynamic_param_names: list[str] = []
        self._dynamic_group_names: list[str] = []
        self._annotations: list[GriptapeAnnotation] = []
        self._expose_knobs: list[ExposedKnob] = []
        self._parsed_nodes: list[ParsedNode] = []

        script_path_param = ParameterString(
            name="script_path",
            default_value="",
            display_name="Script Path (.nk)",
            allow_output=False,
        )
        script_path_param.add_trait(
            FileSystemPicker(allow_files=True, allow_directories=False, file_extensions=[".nk"])
        )
        self.add_parameter(script_path_param)

        try:
            installation_choices = [i.display_name for i in merged_installations(GriptapeNodes.ConfigManager())]
        except Exception:
            installation_choices = []
        if not installation_choices:
            installation_choices = ["(none configured)"]
        nuke_installation_param = Parameter(
            name="nuke_installation",
            type="str",
            default_value=installation_choices[0],
            display_name="Nuke Version",
            tooltip="Select a Nuke installation. Click 'Refresh UI' to repopulate from Engine Settings.",
            allow_output=False,
        )
        nuke_installation_param.add_trait(Options(choices=installation_choices))
        self.add_parameter(nuke_installation_param)

        self.add_parameter(
            Parameter(
                name="frame_start",
                type="int",
                default_value=1001,
                display_name="Frame Start",
                allow_output=False,
            )
        )
        self.add_parameter(
            Parameter(
                name="frame_end",
                type="int",
                default_value=1001,
                display_name="Frame End",
                allow_output=False,
            )
        )
        self.add_parameter(
            ParameterButton(
                name="open_in_nuke",
                label="Open in Nuke",
                tooltip=(
                    "Open Nuke with the Griptape Annotator panel loaded and current overrides pre-applied. "
                    "Use the panel to mark I/O nodes and expose knobs, then save the .gt.json sidecar."
                ),
                variant="secondary",
                full_width=True,
                allow_output=False,
                on_click=self._open_in_nuke,
            )
        )
        self.add_parameter(
            ParameterButton(
                name="refresh_ui",
                label="Refresh UI",
                tooltip="Re-read the .gt.json sidecar and rebuild exposed knob parameters.",
                variant="secondary",
                full_width=True,
                allow_output=False,
                on_click=self._on_refresh_ui,
            )
        )
        advanced_group = ParameterGroup(name="Advanced", collapsed=True)
        self.add_node_element(advanced_group)
        self.add_parameter(
            Parameter(
                name="nuke_executable",
                type="str",
                default_value="",
                display_name="Nuke Executable (override)",
                tooltip="Leave blank to use the nuke.executable engine setting",
                allow_output=False,
                parent_element_name="Advanced",
            )
        )
        baked_path_param = ParameterString(
            name="baked_script_path",
            default_value="",
            display_name="Baked Script Output Path",
            tooltip="Path where the baked .nk copy will be saved (all current values written into the knobs).",
            allow_input=False,
            allow_output=False,
        )
        baked_path_param.add_trait(FileSystemPicker(allow_files=True, allow_directories=False, file_extensions=[".nk"]))
        baked_path_param.parent_element_name = "Advanced"
        self.add_parameter(baked_path_param)
        save_baked_btn = ParameterButton(
            name="save_baked_copy",
            label="Save Baked Copy",
            tooltip="Write a copy of the .nk script with all current parameter values baked into the knobs.",
            variant="secondary",
            full_width=True,
            allow_output=False,
            on_click=self._save_baked_copy,
        )
        save_baked_btn.parent_element_name = "Advanced"
        self.add_parameter(save_baked_btn)
        self._create_status_parameters()

        # Pre-create ParameterGroups from the previous session so that
        # AddParameterToNodeRequest(parent_element_name=...) succeeds during workflow restore.
        # Placed after all static params so the node UI shows static params first.
        # self.metadata is populated by BaseNode.__init__ before we get here.
        for _group_name in (self.metadata or {}).get("_nuke_dynamic_groups", []):
            _group = ParameterGroup(name=_group_name)
            self.add_node_element(_group)
            self._dynamic_group_names.append(_group_name)

        if self._dynamic_group_names:
            self._move_status_to_bottom()

    # ------------------------------------------------------------------
    # Open in Nuke (with Griptape Annotator loaded)
    # ------------------------------------------------------------------

    def _open_in_nuke(
        self,
        button: Button,  # noqa: ARG002
        details: ButtonDetailsMessagePayload,  # noqa: ARG002
    ) -> NodeMessageResult:
        script_path = str(self.get_parameter_value("script_path") or "")
        if not script_path or not os.path.exists(script_path):
            return NodeMessageResult(success=False, details="script_path is not set or the file does not exist.")
        nuke_exe = self._resolve_nuke_exe()
        if not nuke_exe or not os.path.exists(nuke_exe):
            return NodeMessageResult(success=False, details=f"Nuke executable not found: {nuke_exe!r}")

        nuke_path_dirs: list[str] = list(GriptapeNodes.ConfigManager().get_config_value("nuke.nuke_path") or [])
        installation = self._resolve_installation()
        nuke_major = (
            installation.annotator_nuke_version
            if installation is not None
            else int(GriptapeNodes.ConfigManager().get_config_value("nuke.annotator_nuke_version") or 16)
        )
        env: dict[str, str] = {**os.environ, **self._build_env(installation)}
        # Strip third-party Qt plugin paths (e.g. cv2) that shadow Nuke's bundled Qt.
        for _qt_var in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
            env.pop(_qt_var, None)

        try:
            plugin_path = get_plugin_path(nuke_major)
            plugin_path_str = str(plugin_path).replace("\\", "/")
            existing_nuke_path = env.get("NUKE_PATH", "")
            nuke_path_parts = (
                [plugin_path_str]
                + [d for d in nuke_path_dirs if d]
                + ([existing_nuke_path] if existing_nuke_path else [])
            )
            env["NUKE_PATH"] = os.pathsep.join(nuke_path_parts)
        except RuntimeError:
            if nuke_path_dirs:
                env["NUKE_PATH"] = os.pathsep.join(nuke_path_dirs)

        self._ensure_annotations()
        overrides: list[KnobOverride] = []
        for ek in self._expose_knobs:
            raw = self.get_parameter_value(ek.param_name)
            if raw not in (None, ""):
                overrides.append(KnobOverride(node=ek.target_node, knob=ek.target_knob, value=_coerce_knob_value(raw)))

        try:
            cmd, launch_env = _build_open_in_nuke_launch(nuke_exe, script_path, overrides, env)
            subprocess.Popen(cmd, env=launch_env)  # noqa: S603
        except OSError as exc:
            return NodeMessageResult(success=False, details=str(exc))

        return NodeMessageResult(
            success=True,
            details=(
                "Nuke is open with the Griptape Annotator panel. "
                "Open it from Panels > Griptape Annotator, annotate your script, "
                "then save the .gt.json sidecar. "
                "Back in Griptape, re-select the script path to pick up the changes."
            ),
            altered_workflow_state=False,
        )

    # ------------------------------------------------------------------
    # Dynamic port management
    # ------------------------------------------------------------------

    def _on_refresh_ui(
        self,
        button: Button,  # noqa: ARG002
        details: ButtonDetailsMessagePayload,  # noqa: ARG002
    ) -> NodeMessageResult:
        self._refresh_installation_choices()
        script_path = str(self.get_parameter_value("script_path") or "")
        if not script_path or not os.path.exists(script_path):
            return NodeMessageResult(
                success=True, details="Installation choices refreshed.", altered_workflow_state=True
            )
        self._refresh_dynamic_ports(script_path)
        return NodeMessageResult(success=True, details="UI refreshed.", altered_workflow_state=True)

    def _refresh_installation_choices(self) -> None:
        choices = [i.display_name for i in merged_installations(GriptapeNodes.ConfigManager())]
        if not choices:
            choices = ["(none configured)"]
        from griptape_nodes.exe_types.core_types import Trait

        param = self.get_parameter_by_name("nuke_installation")
        if param is None:
            return
        for trait in param.find_elements_by_type(Trait):
            if isinstance(trait, Options):
                trait.choices = choices
                break
        current = self.get_parameter_value("nuke_installation") or ""
        if current not in choices:
            self.set_parameter_value("nuke_installation", choices[0])

    def after_value_set(self, parameter: Parameter, value: Any) -> None:
        if parameter.name == "script_path" and value:
            self._refresh_dynamic_ports(str(value))

    def _refresh_dynamic_ports(self, script_path: str) -> None:  # noqa: C901
        # Absorb any user-defined params not yet tracked — e.g. params left behind by a
        # broken restore where element_modification_commands partially succeeded.
        for p in self.parameters:
            if p.user_defined and p.name not in self._dynamic_param_names:
                self._dynamic_param_names.append(p.name)

        for gname in self._dynamic_group_names:
            self.remove_parameter_element_by_name(gname)
        self._dynamic_group_names.clear()
        for name in self._dynamic_param_names:
            self.remove_parameter_element_by_name(name)
        self._dynamic_param_names.clear()
        self._annotations.clear()
        self._expose_knobs.clear()
        self._parsed_nodes.clear()

        if not os.path.exists(script_path):
            return

        with open(script_path, encoding="utf-8") as f:
            text = f.read()
        self._parsed_nodes = parse_script(text)

        sidecar_path = os.path.splitext(script_path)[0] + ".gt.json"
        if os.path.exists(sidecar_path):
            try:
                annotations, expose_knobs, is_stale = read_sidecar(sidecar_path, script_path)
                if is_stale:
                    print(
                        f"WARNING: {sidecar_path} is stale (script may have been saved after annotation).",
                        flush=True,
                    )
                self._annotations = annotations
                self._expose_knobs = expose_knobs
            except Exception as exc:
                print(
                    f"WARNING: Could not read sidecar {sidecar_path}: {exc}.",
                    flush=True,
                )

        for ann in self._annotations:
            if ann.role != "input":
                continue
            param = Parameter(
                name=ann.gt_name,
                type=ann.gt_type or "str",
                input_types=[
                    "str",
                    "ImageArtifact",
                    "ImageUrlArtifact",
                    "BlobArtifact",
                    "VideoUrlArtifact",
                    "Sequence",
                ],
                default_value="",
                display_name=ann.gt_label or ann.gt_name,
                tooltip=f"Input path for Nuke node {ann.node_name!r}",
                allow_output=False,
                user_defined=True,
            )
            self.add_parameter(param)
            self._dynamic_param_names.append(ann.gt_name)

        has_outputs = any(ann.role == "output" for ann in self._annotations)
        if has_outputs:
            outputs_group = ParameterGroup(name="Outputs")
            self.add_node_element(outputs_group)
            self._dynamic_group_names.append("Outputs")

        for ann in self._annotations:
            if ann.role == "input":
                continue
            if ann.gt_type in {"ThreeDUrlArtifact", "GLTFUrlArtifact"}:
                try:
                    from griptape_nodes.exe_types.param_types.parameter_three_d import (
                        Parameter3D,  # type: ignore[import-not-found]  # noqa: PLC0415
                    )

                    param = Parameter3D(
                        name=ann.gt_name,
                        display_name=ann.gt_label or ann.gt_name,
                        tooltip=f"3D geometry output from Nuke node {ann.node_name!r}",
                        allow_input=False,
                        allow_property=False,
                        user_defined=True,
                    )
                    param.parent_element_name = "Outputs"
                except ImportError:
                    param = Parameter(
                        name=ann.gt_name,
                        type="ThreeDUrlArtifact",
                        default_value="",
                        display_name=ann.gt_label or ann.gt_name,
                        tooltip=f"3D geometry output from Nuke node {ann.node_name!r}",
                        allow_input=False,
                        allow_property=False,
                        user_defined=True,
                        parent_element_name="Outputs",
                    )
            elif ann.gt_type == "ImageSequenceArtifact":
                param = Parameter(
                    name=ann.gt_name,
                    type="Sequence",
                    output_type="Sequence",
                    default_value=None,
                    display_name=ann.gt_label or ann.gt_name,
                    tooltip=f"Image sequence output from Nuke node {ann.node_name!r}",
                    allow_input=False,
                    allow_property=False,
                    user_defined=True,
                    parent_element_name="Outputs",
                )
            else:
                param = Parameter(
                    name=ann.gt_name,
                    type=ann.gt_type or "str",
                    default_value="",
                    display_name=ann.gt_label or ann.gt_name,
                    tooltip=f"Output from Nuke node {ann.node_name!r}",
                    allow_input=False,
                    allow_property=False,
                    user_defined=True,
                    parent_element_name="Outputs",
                )
            self.add_parameter(param)
            self._dynamic_param_names.append(ann.gt_name)

        knob_schema: dict[str, dict] | None = None
        if os.path.exists(sidecar_path):
            knob_schema = read_knob_schema(sidecar_path)

        seen_groups: set[str] = set()
        for ek in self._expose_knobs:
            if ek.param_name in self._dynamic_param_names:
                continue
            group_name = ek.target_node
            if group_name not in seen_groups:
                group = ParameterGroup(name=group_name)
                self.add_node_element(group)
                self._dynamic_group_names.append(group_name)
                seen_groups.add(group_name)
            if ek.knob_type:
                gt_type = griptape_type_for_knob(ek.knob_type)
            else:
                gt_type = resolve_exposed_knob_type(ek.target_node, ek.target_knob, knob_schema)
            # Numeric types use None default (renders as empty number input = no override).
            # String types use "" default for the same semantic.
            default: float | str | None = None if gt_type in {"float", "int"} else ""
            param = Parameter(
                name=ek.param_name,
                type=gt_type,
                default_value=default,
                display_name=ek.target_knob,
                tooltip=f"Override for {ek.knob_ref}",
                allow_output=False,
                user_defined=True,
                parent_element_name=group_name,
            )
            if gt_type == "float":
                param.add_trait(Slider(min_val=-10.0, max_val=10.0))
            self.add_parameter(param)
            self._dynamic_param_names.append(ek.param_name)

        self.metadata["_nuke_dynamic_groups"] = list(self._dynamic_group_names)
        self._move_status_to_bottom()

    def _move_status_to_bottom(self) -> None:
        if not hasattr(self, "status_component"):
            return
        status_group = self.status_component._status_group
        self.remove_node_element(status_group)
        self.add_node_element(status_group)

    def _ensure_annotations(self) -> None:
        """Rebuild _annotations and _expose_knobs from the script if lost across workflow reload."""
        if self._annotations or self._expose_knobs:
            return
        script_path = self.get_parameter_value("script_path") or ""
        if not script_path or not os.path.exists(str(script_path)):
            return
        script_path = str(script_path)
        sidecar_path = os.path.splitext(script_path)[0] + ".gt.json"
        if os.path.exists(sidecar_path):
            annotations, expose_knobs, is_stale = read_sidecar(sidecar_path, script_path)
            if not is_stale:
                self._annotations = annotations
                self._expose_knobs = expose_knobs

    # ------------------------------------------------------------------
    # Artifact / path resolution
    # ------------------------------------------------------------------

    def _artifact_to_path(
        self,
        value: Any,
        name: str = "input",
        _cleanup: list[str] | None = None,
        situation: str = "save_temp_file",
    ) -> str:
        """Resolve a parameter value to a local file path Nuke can read."""
        try:
            from griptape_nodes.common.sequences import Sequence as GtSequence  # type: ignore  # noqa: PLC0415

            if isinstance(value, GtSequence):
                return (value.directory + "/" + value.pattern).replace("\\", "/")
        except ImportError:
            pass
        if isinstance(value, str):
            return value
        try:
            from griptape.artifacts import VideoUrlArtifact  # noqa: PLC0415

            _video_type: type = VideoUrlArtifact
        except ImportError:
            _video_type = type(None)
        val = getattr(value, "value", None)
        if isinstance(val, str):
            if val.startswith(("http://", "https://")):
                detected = os.path.splitext(val.split("?")[0])[-1]
                suffix = detected or (".mp4" if isinstance(value, _video_type) else ".png")
                _id = uuid.uuid4().hex[:8]
                # Download the remote asset into a project-managed file so Nuke can read it
                # by local path. UUID prefix avoids collisions when multiple nodes run in
                # parallel. final_file_path (not resolve()) is used because the framework may
                # rename the file under CREATE_NEW collision policy.
                dest = ProjectFileDestination.from_situation(f"{self.name}_{name}_{_id}{suffix}", situation)
                with urllib.request.urlopen(val, timeout=30) as response:  # noqa: S310
                    tmp_path = self._write_scratch_file(str(dest.resolve()), response.read())
                if _cleanup is not None:
                    _cleanup.append(tmp_path)
                return tmp_path
            if "{" in val:
                try:
                    macro = ParsedMacro(val)
                except MacroSyntaxError:
                    macro = None
                if macro is not None:
                    result = GriptapeNodes.handle_request(GetPathForMacroRequest(parsed_macro=macro, variables={}))
                    if isinstance(result, GetPathForMacroResultSuccess):
                        return str(result.absolute_path)
            return val
        if isinstance(val, bytes):
            _id = uuid.uuid4().hex[:8]
            # Materialise raw bytes (e.g. BlobArtifact image data) to a file Nuke can open.
            # Same UUID + situation strategy as the URL branch above.
            dest = ProjectFileDestination.from_situation(f"{self.name}_{name}_{_id}.png", situation)
            tmp_path = self._write_scratch_file(str(dest.resolve()), val)
            if _cleanup is not None:
                _cleanup.append(tmp_path)
            return tmp_path
        return str(value)

    def _write_scratch_file(self, path: str, content: bytes) -> str:
        """Write content and return the canonical path actually written.

        The framework may rename the file (e.g. foo_1.png) under a CREATE_NEW collision
        policy, so callers must use final_file_path rather than the path they passed in.
        """
        result = GriptapeNodes.handle_request(WriteFileRequest(file_path=path, content=content))
        if not isinstance(result, WriteFileResultSuccess):
            raise RuntimeError(f"Failed to write scratch file: {path}")
        return result.final_file_path

    def _build_env(self, installation: NukeInstallation | None) -> dict[str, str]:
        """Merge global env settings, installation overrides, and foundry_LICENSE from os.environ."""
        global_env: dict[str, str] = GriptapeNodes.ConfigManager().get_config_value("nuke.env") or {}
        install_env: dict[str, str] = installation.env_overrides if installation else {}
        env = {**global_env, **install_env}
        if fl := os.environ.get("foundry_LICENSE"):
            env.setdefault("foundry_LICENSE", fl)
        return env

    def _resolve_installation(self) -> NukeInstallation | None:
        selected = str(self.get_parameter_value("nuke_installation") or "")
        if selected and selected != "(none configured)":
            return find_installation(selected, GriptapeNodes.ConfigManager())
        return None

    def _resolve_nuke_exe(self) -> str:
        override = self.get_parameter_value("nuke_executable") or ""
        if override:
            return str(override)
        inst = self._resolve_installation()
        if inst:
            return inst.executable_path
        return GriptapeNodes.ConfigManager().get_config_value("nuke.executable") or ""

    # ------------------------------------------------------------------
    # Validation and execution
    # ------------------------------------------------------------------

    def validate_before_node_run(self) -> list[Exception] | None:
        self._ensure_annotations()
        errors: list[Exception] = []

        script_path = self.get_parameter_value("script_path") or ""
        if not script_path:
            errors.append(ValueError("script_path is required"))
        elif not os.path.exists(str(script_path)):
            errors.append(FileNotFoundError(f"Script not found: {script_path}"))

        nuke_exe = self._resolve_nuke_exe()
        if not nuke_exe:
            errors.append(ValueError("nuke_executable is not set and nuke.executable engine setting is empty"))
        elif not os.path.exists(nuke_exe):
            errors.append(FileNotFoundError(f"Nuke executable not found: {nuke_exe}"))

        return errors or None

    def _save_baked_copy(
        self,
        button: Button,  # noqa: ARG002
        details: ButtonDetailsMessagePayload,  # noqa: ARG002
    ) -> NodeMessageResult:
        self._ensure_annotations()
        script_path = self.get_parameter_value("script_path")
        baked_path = self.get_parameter_value("baked_script_path")

        if not script_path or not os.path.exists(str(script_path)):
            return NodeMessageResult(success=False, details="No valid script_path set.", altered_workflow_state=False)
        if not baked_path:
            return NodeMessageResult(
                success=False, details="Set 'Baked Script Output Path' first.", altered_workflow_state=False
            )

        installation = self._resolve_installation()
        nuke_exe = self._resolve_nuke_exe()
        if not nuke_exe:
            return NodeMessageResult(
                success=False, details="Nuke executable not configured.", altered_workflow_state=False
            )

        nuke_path_dirs: list[str] = GriptapeNodes.ConfigManager().get_config_value("nuke.nuke_path") or []
        env = self._build_env(installation)
        if nuke_path_dirs:
            env["NUKE_PATH"] = os.pathsep.join(nuke_path_dirs)

        inputs: dict[str, ManifestInput] = {}
        for ann in self._annotations:
            if ann.role == "input":
                raw = self.get_parameter_value(ann.gt_name) or ""
                if raw:
                    # Paths are baked as absolute references into the .nk copy, so they must
                    # outlive this call. Persist them as node outputs, not temp files.
                    inputs[ann.gt_name] = ManifestInput(
                        path=self._artifact_to_path(raw, name=ann.gt_name, situation="save_node_output"),
                        node=ann.node_name,
                    )

        knob_overrides: list[KnobOverride] = []
        for ek in self._expose_knobs:
            raw = self.get_parameter_value(ek.param_name)
            if raw not in (None, ""):
                knob_overrides.append(
                    KnobOverride(node=ek.target_node, knob=ek.target_knob, value=_coerce_knob_value(raw))
                )

        manifest = JobManifest(
            script=str(script_path),
            inputs=inputs,
            outputs={},
            knob_overrides=knob_overrides,
            env=env,
            bake_output_path=str(baked_path),
        )
        provider = DirectSubprocessProvider(
            nuke_exe=nuke_exe, runner_script=_BAKE_RUNNER_SCRIPT, installation=installation
        )
        result = provider.result(provider.submit(manifest))

        if result.return_code != 0:
            log_tail = "\n".join(result.log[-10:]) if result.log else "(no output)"
            return NodeMessageResult(
                success=False,
                details=f"Bake failed (exit {result.return_code}):\n{log_tail}",
                altered_workflow_state=False,
            )
        return NodeMessageResult(
            success=True,
            details=f"Baked copy saved to:\n{baked_path}",
            altered_workflow_state=False,
        )

    def process(self) -> None:
        self._clear_execution_status()
        self._ensure_annotations()

        script_path = str(self.get_parameter_value("script_path"))
        installation = self._resolve_installation()
        nuke_exe = self._resolve_nuke_exe()
        frame_start = int(self.get_parameter_value("frame_start") or 1001)
        frame_end = int(self.get_parameter_value("frame_end") or 1001)

        nuke_path_dirs: list[str] = GriptapeNodes.ConfigManager().get_config_value("nuke.nuke_path") or []
        env = self._build_env(installation)
        if nuke_path_dirs:
            env["NUKE_PATH"] = os.pathsep.join(nuke_path_dirs)

        inputs: dict[str, ManifestInput] = {}
        outputs: dict[str, ManifestOutput] = {}
        input_tmp_paths: list[str] = []
        output_tmp_paths: list[str] = []
        _run_id = uuid.uuid4().hex[:8]

        try:
            for ann in self._annotations:
                if ann.role == "input":
                    inputs[ann.gt_name] = ManifestInput(
                        path=self._artifact_to_path(
                            self.get_parameter_value(ann.gt_name) or "",
                            name=ann.gt_name,
                            _cleanup=input_tmp_paths,
                        ),
                        node=ann.node_name,
                    )
                elif ann.gt_type == "ImageSequenceArtifact":
                    macro_result = GriptapeNodes.handle_request(
                        GetPathForMacroRequest(
                            parsed_macro=ParsedMacro("{outputs}/nuke/{node_name}/{param_name}/frame_####.png"),
                            variables={"node_name": self.name, "param_name": ann.gt_name},
                        )
                    )
                    if not isinstance(macro_result, GetPathForMacroResultSuccess):
                        raise RuntimeError(f"Could not resolve output path for sequence {ann.gt_name!r}")
                    seq_path = str(macro_result.absolute_path).replace("\\", "/")
                    os.makedirs(os.path.dirname(seq_path), exist_ok=True)
                    outputs[ann.gt_name] = ManifestOutput(
                        path=seq_path,
                        node=ann.node_name,
                        type="ImageSequenceArtifact",
                    )
                else:
                    suffix = _TEMP_SUFFIX.get(ann.gt_type or "", ".png")
                    placeholder_dest = ProjectFileDestination.from_situation(
                        f"{self.name}_{_run_id}_{ann.gt_name}{suffix}", "save_temp_file"
                    )
                    # Pre-create the output file so Nuke has a known path to write into.
                    # The runner overwrites this placeholder; after the run _path_to_artifact
                    # reads it and re-saves to save_node_output so downstream nodes get a
                    # persistent URL. The placeholder is cleaned up in the finally block.
                    placeholder_path = self._write_scratch_file(str(placeholder_dest.resolve()), b"")
                    output_tmp_paths.append(placeholder_path)
                    outputs[ann.gt_name] = ManifestOutput(
                        path=placeholder_path,
                        node=ann.node_name,
                        type=ann.gt_type or "ImageArtifact",
                    )

            knob_overrides: list[KnobOverride] = []
            for ek in self._expose_knobs:
                raw = self.get_parameter_value(ek.param_name)
                if raw not in (None, ""):
                    knob_overrides.append(
                        KnobOverride(node=ek.target_node, knob=ek.target_knob, value=_coerce_knob_value(raw))
                    )

            manifest = JobManifest(
                script=script_path,
                inputs=inputs,
                outputs=outputs,
                knob_overrides=knob_overrides,
                frame_range=[frame_start, frame_end],
                env=env,
            )
            provider = DirectSubprocessProvider(
                nuke_exe=nuke_exe, runner_script=_RUNNER_SCRIPT, installation=installation
            )
            result = provider.result(provider.submit(manifest))

            if result.return_code != 0:
                log_tail = "\n".join(result.log[-20:]) if result.log else "(no output)"
                msg = f"Nuke exited with return code {result.return_code}:\n{log_tail}"
                self._set_status_results(was_successful=False, result_details=f"FAILURE: {msg}")
                self._handle_failure_exception(RuntimeError(msg))
                return

            for gt_name, path in result.outputs.items():
                if gt_name not in outputs:
                    logging.getLogger(__name__).warning("Nuke runner returned unknown output key %r; skipping", gt_name)
                    continue
                ann_type = outputs[gt_name].type
                if ann_type == "ImageSequenceArtifact":
                    from griptape_nodes.retained_mode.events.os_events import ScanSequencesRequest  # type: ignore  # noqa: PLC0415, I001
                    from griptape_nodes.retained_mode.events.os_events import ScanSequencesResultSuccess  # type: ignore  # noqa: PLC0415, I001

                    scan_result = GriptapeNodes.handle_request(
                        ScanSequencesRequest(
                            path=path,
                            start_number=frame_start,
                            end_number=frame_end,
                        )
                    )
                    if isinstance(scan_result, ScanSequencesResultSuccess) and scan_result.sequences:  # pyright: ignore[reportAttributeAccessIssue]
                        self.parameter_output_values[gt_name] = scan_result.sequences[0]  # pyright: ignore[reportAttributeAccessIssue]
                    else:
                        raise RuntimeError(f"No frames found for sequence at {path!r}")
                else:
                    self.parameter_output_values[gt_name] = _path_to_artifact(ann_type, path)

            self._set_status_results(was_successful=True, result_details="Render complete.")
        finally:
            for p in input_tmp_paths + output_tmp_paths:
                GriptapeNodes.handle_request(DeleteFileRequest(path=p, workspace_only=False))
