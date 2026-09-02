#!/usr/bin/env python
"""Generic runner script bundled alongside a Griptape Nodes gizmo.

This script is copied into the gizmo companion directory at publish time
and invoked by the gizmo's "Run Workflow" button via subprocess.

Usage:
    python run_workflow.py \\
        --workflow-file /path/to/workflow.py \\
        --json-input '{"Nuke Start Flow": {"prompt": "...", "input_image": "..."}}' \\
        --output-dir /path/to/output

Output:
    Prints a JSON dict to stdout mapping output parameter names to their
    string-serialized values (file paths for images, strings for text).
    Exit code 0 on success, non-zero on failure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Redirect the engine's USER config off the user's global ~/.config/griptape_nodes
# so per-run project paths (and any other engine writes) never pollute it.  Must
# be set before any griptape_nodes import because xdg_config_home() is evaluated
# once at config_manager import time.  The guard lets run_button.py's explicit
# env= take precedence — in normal gizmo runs the parent always sets this to a
# per-machine dir.  This fallback only fires for standalone/debug invocations of
# this script; it points at a per-machine path (never the possibly-shared bundle)
# so a bundle on a read-only or shared drive can't break the run.
if not os.environ.get("XDG_CONFIG_HOME"):
    _data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    _config_home = Path(_data_home) / "griptape_nodes" / "gizmo_standalone_config"
    os.environ["XDG_CONFIG_HOME"] = str(_config_home).replace("\\", "/")

import argparse  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import subprocess  # noqa: E402

from dotenv import dotenv_values
from output_paths import (
    OutputDirResolution,
    ProjectActivation,
    activate_project,
    default_output_dir,
    normalize_for_nuke,
    resolve_output_dir,
    serialize_output,
)
from output_protocol import emit_payload

logger = logging.getLogger(__name__)

# The bundled project.yml's ``outputs`` directory references only this variable, so the
# runner must always export it.
OUTPUTS_DIR_ENV_VAR = "GTN_NUKE_GIZMO_OUTPUTS_DIR"

# Every other writable directory in the bundled project.yml is anchored on this
# variable.
SCRIPT_DIR_ENV_VAR = "GTN_NUKE_GIZMO_SCRIPT_DIR"

# Hidden directory, beside the artist's .nk script, holding everything a run writes apart
# from its outputs.
GRIPTAPE_RUN_DIR_NAME = ".griptape"


def _load_bundled_env(env_path: Path) -> None:
    """Apply the bundled .env, letting a meaningful parent value win but never a blank one.

    The bundled .env only fills variables the parent Nuke process did not already
    set, so a pipeline/farm job can supply its own credentials (e.g. a per-job
    GT_CLOUD_API_KEY) without being clobbered.  ``load_dotenv(override=False)``
    cannot express that on its own: python-dotenv defers on key *presence*, so a
    blank ``GT_CLOUD_API_KEY=""`` inherited from Nuke's environment shadows a
    valid key in the bundle and the published gizmo fails as if no credential
    were configured.  A blank carries no credential to defer to, so treat it the
    same as absent -- on both sides.  Blanks in the bundle are dropped rather than
    exported, because the engine's own secret lookup checks os.environ first and a
    blank there reads as a configured empty credential; bundles published before
    blank-valued secrets were filtered out still carry them.
    """
    for key, value in dotenv_values(env_path).items():
        if not value or os.environ.get(key):
            continue
        os.environ[key] = value


def _bootstrap_environment() -> None:
    """Pin workspace_path to the bundle root, matching Local/Cloud's entrypoints."""
    script_dir = Path(__file__).parent

    env_path = script_dir / ".env"
    if env_path.exists():
        _load_bundled_env(env_path)

    # Workspace path must be the bundle root since the bundled workflow may contain relative paths.
    os.environ["GTN_CONFIG_WORKSPACE_DIRECTORY"] = str(script_dir)
    os.environ["GTN_CONFIG_ENABLE_WORKSPACE_FILE_WATCHING"] = "false"

    # Supply the project file path if not already set.  The project.yml
    # always lives in the companion bundle regardless of the workspace.
    project_yml = script_dir / "project.yml"
    if project_yml.exists() and "--project-file-path" not in sys.argv:
        sys.argv.extend(["--project-file-path", str(project_yml)])


def _load_workflow_module(workflow_file: str):
    """Dynamically load a workflow .py file as a Python module.

    The workflow file's top-level code runs on import, registering the
    libraries and building the node graph in memory.
    """
    spec = importlib.util.spec_from_file_location("_griptape_workflow", workflow_file)
    if spec is None or spec.loader is None:
        msg = f"Could not load workflow module from: {workflow_file}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_griptape_workflow"] = module
    spec.loader.exec_module(module)
    return module


def _log_interpreter() -> None:
    """Log which interpreter is running and whether a host PYTHONPATH leaked in.

    run_button.py streams this to the gizmo's progress dialog, so an environment
    leak (a wrapper's site-packages shadowing the venv) is visible at a glance
    instead of surfacing as a bare ImportError from deep inside the engine.
    """
    logger.info("Interpreter: %s", sys.executable)
    logger.info("Python version: %s", sys.version.split()[0])
    logger.info("PYTHONPATH: %s", os.environ.get("PYTHONPATH", "") or "(empty)")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    _log_interpreter()

    parser = argparse.ArgumentParser(description="Run a Griptape Nodes workflow from a gizmo.")
    parser.add_argument("--workflow-file", required=True, help="Path to the workflow .py file")
    parser.add_argument("--json-input", required=True, help="JSON dict of workflow inputs")
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory workflow outputs are written to. Left blank, outputs go to a 'griptape_outputs' folder "
            "next to the .nk script. A relative path is anchored to the .nk script's directory. An absolute "
            "path is used as-is. Macros in braces, such as {outputs}, are resolved against the bundle's own "
            "project.yml, falling back to this process's environment for any name that project does not "
            "define. Avoid the built-ins {project_dir}, {workflow_dir}, {workspace_dir} and {inputs}, which "
            "resolve to a location inside the installed gizmo, and {workflow_name}, which is resolved before "
            "the workflow is loaded, so there is no workflow to name yet and it never resolves. If any name "
            "cannot be resolved, the run stops with an error naming it and nothing is rendered."
        ),
    )
    parser.add_argument(
        "--nk-script-dir",
        default=None,
        help="Absolute Nuke script directory; the outputs directory macro resolves next to this file",
    )
    parser.add_argument(
        "--storage-backend",
        choices=["local", "gtc"],
        default="local",
        help="Storage backend for the workflow executor",
    )
    args = parser.parse_args()

    # This same value is handed to _export_outputs_dir below, where it anchors the outputs
    # directory. A relative value reaching there would silently anchor outputs under the
    # wrong directory, so it is rejected here before anything else runs.
    nk_script_dir = args.nk_script_dir
    if nk_script_dir is not None and not Path(nk_script_dir).is_absolute():
        emit_payload({"error": f"--nk-script-dir must be an absolute path, got: {nk_script_dir!r}"})
        sys.exit(1)

    workflow_file = Path(args.workflow_file)
    if not workflow_file.is_file():
        emit_payload({"error": f"Workflow file not found: {workflow_file}"})
        sys.exit(1)

    try:
        flow_input = json.loads(args.json_input)
    except json.JSONDecodeError as e:
        emit_payload({"error": f"Invalid --json-input: {e}"})
        sys.exit(1)

    # Bootstrap environment before loading workflow.
    _bootstrap_environment()

    script_dir = Path(__file__).parent
    bundle_project_file = script_dir / "project.yml"

    # Export env var that will be interpolated into the project on activation.
    anchor_dir = _export_script_dir(nk_script_dir, script_dir)
    # Redirect the writable directories project.yml cannot reach, before the engine is built.
    _export_engine_config_directories(anchor_dir)
    # Activate project in case the knob contains macros.
    _activate_bundle_project(bundle_project_file)
    # Resolve and export the knob value as an environment variable, referenced in
    # project.yml.
    _export_outputs_dir(args.output_dir, nk_script_dir, script_dir)

    # Eagerly register the bundled libraries before the workflow module loads.
    # The workflow uses name-based RegisterLibraryFromFileRequest, which only
    # succeeds if the library is already known to the engine — and the
    # libraries_to_register entries in griptape_nodes_config.json are not
    # read until later.
    try:
        from register_libraries_script import register_bundled_libraries

        register_bundled_libraries()
    except Exception as e:
        # This is the message an artist copies into a bug report, and the usual cause
        # is a host env var pointing the interpreter at foreign packages -- so name the
        # interpreter and any leaked PYTHONPATH here rather than only in the log stream.
        print(
            json.dumps(
                {
                    "error": (
                        f"Failed to register bundled libraries: {e}"
                        f" [interpreter={sys.executable} python={sys.version.split()[0]}"
                        f" PYTHONPATH={os.environ.get('PYTHONPATH', '') or '(empty)'}]"
                    )
                }
            )
        )
        sys.exit(1)

    # Download HuggingFace models if a download script was bundled at publish time.
    # If a local HuggingFace cache already exists on this machine, point the subprocess
    # at it via HF_HUB_CACHE so that cached models are reused instead of re-downloaded.
    download_script = script_dir / "download_models.py"
    if download_script.exists():
        download_env = os.environ.copy()
        if "HF_HUB_CACHE" not in download_env and "HF_HOME" not in download_env:
            default_hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
            if default_hf_cache.is_dir():
                download_env["HF_HUB_CACHE"] = str(default_hf_cache)
        download_result = subprocess.run(
            [sys.executable, str(download_script)],
            env=download_env,
        )
        if download_result.returncode != 0:
            emit_payload({"error": "Model download failed. See log output for details."})
            sys.exit(1)

    try:
        module = _load_workflow_module(str(workflow_file))
    except Exception as e:
        emit_payload({"error": f"Failed to load workflow: {e}"})
        sys.exit(1)

    if not hasattr(module, "execute_workflow"):
        emit_payload({"error": "Workflow module has no execute_workflow() function"})
        sys.exit(1)

    try:
        output = module.execute_workflow(
            input=flow_input,
            project_file_path=str(bundle_project_file),
        )
    except Exception as e:
        emit_payload({"error": f"Workflow execution failed: {e}"})
        sys.exit(1)
    else:
        try:
            result = serialize_output(output)
        except Exception as e:
            emit_payload({"error": f"Failed to serialize output after a successful run: {e}"})
            sys.exit(1)

    emit_payload(result)


def _export_script_dir(nk_script_dir: str | None, script_dir: Path) -> str:
    """Export SCRIPT_DIR_ENV_VAR: the anchor the bundle's writable directories all hang off."""
    # An unsaved .nk script has no directory to sit beside, so this falls back to the
    # bundle root - see default_output_dir().
    anchor = normalize_for_nuke(nk_script_dir or str(script_dir))
    os.environ[SCRIPT_DIR_ENV_VAR] = anchor
    return anchor


def _export_engine_config_directories(anchor_dir: str) -> None:
    """Redirect the two writable engine directories that come from config rather than project.yml.

    GTN_CONFIG_ variables are the highest-precedence config layer and are read in memory only,
    unlike a written config value, which would persist into the artist's own user config.
    """
    # StaticFilesManager clamps a resolved path back inside the workspace; the fallback arm it
    # lands in rebuilds the path from this raw config value without re-validating, so an absolute
    # value escapes the clamp. Left alone, static files are written inside the bundle.
    os.environ["GTN_CONFIG_STATIC_FILES_DIRECTORY"] = normalize_for_nuke(
        f"{anchor_dir}/{GRIPTAPE_RUN_DIR_NAME}/staticfiles"
    )

    # Scratch for cloud workflow sync, which a gizmo run never uses, so it has no business in the
    # artist's shot folder. Nor may it sit under the bundle: SyncManager.__init__ mkdir's it
    # unguarded during Engine.__init__, so a read-only install hard-crashes before the runner can
    # report anything. A per-machine location is writable either way.
    os.environ["GTN_CONFIG_SYNCED_WORKFLOWS_DIRECTORY"] = normalize_for_nuke(_per_machine_synced_workflows_dir())


def _activate_bundle_project(bundle_project_file: Path) -> ProjectActivation:
    """Make the bundle's own project current, or abort: every later macro resolves through it."""
    activation = activate_project(bundle_project_file)
    if not activation.succeeded:
        emit_payload({"error": _activation_abort_message(bundle_project_file, activation)})
        sys.exit(1)
    return activation


def _export_outputs_dir(output_dir_arg: str | None, nk_script_dir: str | None, script_dir: Path) -> None:
    """Resolve the Output Directory knob and export it as OUTPUTS_DIR_ENV_VAR, or abort before anything runs."""
    # In case the user included `{outputs}` in the knob value (i.e. output_dir_arg).
    os.environ[OUTPUTS_DIR_ENV_VAR] = default_output_dir(nk_script_dir, str(script_dir))
    resolution = resolve_output_dir(output_dir_arg, nk_script_dir, str(script_dir))
    # Abort if resolution failed, e.g. a required macro could not be substituted.
    if resolution.path is None:
        emit_payload({"error": _output_dir_abort_message(resolution)})
        sys.exit(1)

    logger.info("Output directory: %s", resolution.path)
    os.environ[OUTPUTS_DIR_ENV_VAR] = resolution.path


def _per_machine_synced_workflows_dir() -> str:
    """Return a writable per-machine location for the engine's synced-workflows directory.

    Derived the same way as run_button.py's venv root, and unconditionally: the
    XDG_CONFIG_HOME fallback at the top of this module only computes a base when the parent
    left that variable unset.
    """
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return f"{data_home}/griptape_nodes/gizmo_standalone/synced_workflows"


def _activation_abort_message(bundle_project_file: Path, activation: ProjectActivation) -> str:
    """Compose the abort text for a bundle whose project.yml could not be made the current project."""
    message = (
        "Attempted to work out where this gizmo's outputs should be written, using the project "
        f"settings published with the gizmo at {bundle_project_file}. "
        f"Failed due to {activation.failure_reason}. "
        "Republish the gizmo from Griptape Nodes to rebuild its bundle, then try again."
    )

    if activation.engine_detail is None:
        return message

    return f"{message} Technical detail from the engine: {activation.engine_detail}"


def _output_dir_abort_message(resolution: OutputDirResolution) -> str:
    """Compose the abort text for an Output Directory the engine could not turn into a path."""
    message = (
        "Attempted to work out where this gizmo's outputs should be written, from the Output "
        f"Directory '{resolution.raw_text}'. "
        f"Failed due to {_unresolved_name_cause(resolution.missing_variables)}. "
        "Nothing has been rendered. Check the spelling, or clear the Output Directory to write "
        "next to the .nk script instead, then run again."
    )

    if resolution.failure_reason is None:
        return message

    return f"{message} Technical detail from the engine: {resolution.failure_reason}"


def _unresolved_name_cause(missing_variables: tuple[str, ...]) -> str:
    """Name the variables the engine could not resolve, or say only that the text was unreadable."""
    if not missing_variables:
        return "that text not being readable as a path"

    named = ", ".join(f"'{name}'" for name in missing_variables)
    plural = "s" if len(missing_variables) > 1 else ""
    return f"there being no variable{plural} named {named}"


if __name__ == "__main__":
    main()
