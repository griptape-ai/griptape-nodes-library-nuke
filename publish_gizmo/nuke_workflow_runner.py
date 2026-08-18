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
import tempfile  # noqa: E402

from dotenv import load_dotenv
from griptape_nodes.common.project_templates.directory import DirectoryDefinition
from output_paths import build_macro_map, load_project_template, resolve_output_dir, serialize_output
from output_protocol import emit_payload

logger = logging.getLogger(__name__)


def _bootstrap_environment(nk_script_dir: str | None = None) -> None:
    """Load .env and set workspace config, matching LocalPublisher's run.py entrypoint.

    Args:
        nk_script_dir: If provided, use this as the workspace directory so that
            project directory macros (``{outputs}``, ``{inputs}``, etc.) resolve
            relative to the Nuke script rather than the companion bundle.  When
            *None*, the companion directory is used (original behaviour).
    """
    script_dir = Path(__file__).parent

    # Load .env with python-dotenv (handles quoted values correctly).
    # override=False: the bundled .env only fills env vars the parent Nuke
    # process did not already set, so a pipeline/farm job can supply its own
    # credentials (e.g. per-job GT_CLOUD_API_KEY) without being clobbered.
    env_path = script_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)

    # When a Nuke script directory is available, use it as the workspace so
    # that relative directory macros in project.yml (like ``outputs``) resolve
    # next to the .nk file instead of inside the companion bundle.
    workspace_dir = nk_script_dir if nk_script_dir else str(script_dir)
    os.environ["GTN_CONFIG_WORKSPACE_DIRECTORY"] = workspace_dir
    os.environ["GTN_ENABLE_WORKSPACE_FILE_WATCHING"] = "false"

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


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Run a Griptape Nodes workflow from a gizmo.")
    parser.add_argument("--workflow-file", required=True, help="Path to the workflow .py file")
    parser.add_argument("--json-input", required=True, help="JSON dict of workflow inputs")
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Override for the {outputs} directory macro. An absolute path is used as-is; a relative path is "
            "anchored to --nk-script-dir (the companion bundle when the script is unsaved); project directory "
            "macros such as {inputs} are resolved against the bundle's project.yml"
        ),
    )
    parser.add_argument(
        "--nk-script-dir",
        default=None,
        help="Nuke script directory; used as workspace so project directory macros resolve next to the .nk file",
    )
    parser.add_argument(
        "--storage-backend",
        choices=["local", "gtc"],
        default="local",
        help="Storage backend for the workflow executor",
    )
    args = parser.parse_args()

    workflow_file = Path(args.workflow_file)
    if not workflow_file.is_file():
        emit_payload({"error": f"Workflow file not found: {workflow_file}"})
        sys.exit(1)

    try:
        flow_input = json.loads(args.json_input)
    except json.JSONDecodeError as e:
        emit_payload({"error": f"Invalid --json-input: {e}"})
        sys.exit(1)

    # Bootstrap environment before loading workflow (needs .env for API keys etc.)
    _bootstrap_environment(nk_script_dir=args.nk_script_dir)

    # Resolve the requested output directory once, up front.  Both the engine's
    # save path and the path reported back to Nuke are derived from this single
    # absolute value, so a relative knob value can't be resolved two different
    # ways (which left Nuke's Read node unable to open a file that was written).
    # The macro map is built from the bundle's project.yml before any override is
    # installed, so a {outputs}-relative knob value resolves against the authored
    # directory instead of becoming a self-reference the engine reads as a cycle.
    script_dir = Path(__file__).parent
    workspace_dir = Path(args.nk_script_dir) if args.nk_script_dir else None
    macro_map = build_macro_map(script_dir, workspace_dir=workspace_dir)
    output_dir = resolve_output_dir(args.output_dir, args.nk_script_dir, str(script_dir), macro_map)
    if output_dir:
        logger.info("Output directory: %s", output_dir)

    # Eagerly register the bundled libraries before the workflow module loads.
    # The workflow uses name-based RegisterLibraryFromFileRequest, which only
    # succeeds if the library is already known to the engine — and the
    # libraries_to_register entries in griptape_nodes_config.json are not
    # always picked up on a fresh user machine.
    try:
        from register_libraries_script import register_bundled_libraries

        register_bundled_libraries()
    except Exception as e:
        print(json.dumps({"error": f"Failed to register bundled libraries: {e}"}))
        sys.exit(1)

    # Download HuggingFace models if a download script was bundled at publish time.
    # If a local HuggingFace cache already exists on this machine, point the subprocess
    # at it via HF_HUB_CACHE so that cached models are reused instead of re-downloaded.
    download_script = Path(__file__).parent / "download_models.py"
    if download_script.exists():
        download_env = os.environ.copy()
        if "HF_HUB_CACHE" not in download_env and "HF_HOME" not in download_env:
            default_hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
            if default_hf_cache.is_dir():
                download_env["HF_HUB_CACHE"] = str(default_hf_cache)
        result = subprocess.run(
            [sys.executable, str(download_script)],
            env=download_env,
        )
        if result.returncode != 0:
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

    bundle_project_file = script_dir / "project.yml"

    # When an output directory is specified, build a per-run temp project.yml that
    # redirects {outputs} to the requested directory.  The bundle's situation macro
    # and OVERWRITE policy are kept exactly as authored — only the directory changes.
    # This makes the engine's actual save path agree with the path we report to Nuke.
    # The bundle file itself is never modified.
    temp_project_file = None
    project_file_path: str | None = str(bundle_project_file) if bundle_project_file.exists() else None

    if output_dir:
        template = load_project_template(bundle_project_file)
        if template is not None:
            template.directories["outputs"] = DirectoryDefinition(
                name="outputs",
                path_macro=output_dir,
            )
            tmp = tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".yml",
                prefix="griptape_nuke_run_",
                delete=False,
                encoding="utf-8",
            )
            temp_project_file = tmp.name  # register for cleanup before any write can raise
            project_file_path = temp_project_file
            tmp.write(template.to_yaml())
            tmp.close()

    try:
        output = module.execute_workflow(
            input=flow_input,
            project_file_path=project_file_path,
        )
    except Exception as e:
        emit_payload({"error": f"Workflow execution failed: {e}"})
        sys.exit(1)
    finally:
        if temp_project_file is not None:
            try:
                Path(temp_project_file).unlink(missing_ok=True)
            except OSError:
                pass

    if output_dir:
        macro_map["outputs"] = output_dir
    result = serialize_output(output, macro_map)
    emit_payload(result)


if __name__ == "__main__":
    main()
