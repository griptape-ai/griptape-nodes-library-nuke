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

import argparse
import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from griptape_nodes.common.project_templates import load_project_template_from_yaml
from griptape_nodes.common.project_templates.validation import ProjectValidationInfo, ProjectValidationStatus


def _bootstrap_environment() -> None:
    """Load .env and set workspace config, matching LocalPublisher's run.py entrypoint."""
    script_dir = Path(__file__).parent

    # Load .env with python-dotenv (handles quoted values correctly)
    env_path = script_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # Set workspace directory to this script's directory
    os.environ["GTN_CONFIG_WORKSPACE_DIRECTORY"] = str(script_dir)
    os.environ["GTN_ENABLE_WORKSPACE_FILE_WATCHING"] = "false"

    # Supply the project file path if not already set
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


def _build_macro_map(script_dir: Path) -> dict[str, str]:
    """Build a map of macro names to absolute paths from the project.yml.

    The project system stores output values in macro form (e.g. {outputs}/file.jpg).
    This map lets us resolve those macros to real paths that Nuke can open.
    """
    project_yml = script_dir / "project.yml"
    if not project_yml.exists():
        return {}

    validation_info = ProjectValidationInfo(status=ProjectValidationStatus.GOOD)
    template = load_project_template_from_yaml(project_yml.read_text(encoding="utf-8"), validation_info)
    if template is None:
        return {}

    # Resolve relative macros against script_dir so the companion bundle is portable.
    # Absolute path_macros (e.g. from a legacy publish) are kept as-is.
    result = {}
    for dir_def in template.directories.values():
        value = dir_def.path_macro
        if value and not Path(value).is_absolute():
            value = str(script_dir / value)
        result[dir_def.name] = value
    return result


def _resolve_macro_path(value: str, macro_map: dict[str, str]) -> str:
    """Replace {outputs}, {inputs}, etc. in a path string with their resolved values."""
    if "{" not in value:
        return value

    def _replace(match: re.Match) -> str:
        return macro_map.get(match.group(1), match.group(0))

    return re.sub(r"\{([\w-]+)\}", _replace, value)


def _serialize_output(output: dict | None, macro_map: dict[str, str]) -> dict[str, str]:
    """Flatten and serialize the workflow output dict for JSON printing.

    The executor returns a nested dict: {node_name: {param_name: value}}.
    We flatten it to {param_name: str(value)} for the gizmo to consume.
    Image artifacts expose a .url or .value attribute that contains the path.
    Macro paths like {outputs}/file.jpg are resolved to absolute paths.
    """
    if not output:
        return {}

    result: dict[str, str] = {}
    for _node_name, params in output.items():
        if not isinstance(params, dict):
            continue
        for param_name, value in params.items():
            if value is None:
                result[param_name] = ""
            elif hasattr(value, "url"):
                # ImageUrlArtifact — strip file:// prefix for usability in Nuke
                url = str(value.url)
                if url.startswith("file://"):
                    url = url[7:]
                result[param_name] = _resolve_macro_path(url, macro_map)
            elif hasattr(value, "value") and isinstance(value.value, (str, bytes)):
                raw = value.value
                if isinstance(raw, bytes):
                    result[param_name] = f"<binary {len(raw)} bytes>"
                else:
                    result[param_name] = _resolve_macro_path(raw, macro_map)
            else:
                result[param_name] = _resolve_macro_path(str(value), macro_map)

    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Run a Griptape Nodes workflow from a gizmo.")
    parser.add_argument("--workflow-file", required=True, help="Path to the workflow .py file")
    parser.add_argument("--json-input", required=True, help="JSON dict of workflow inputs")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for output files (used as project_file_path for local storage)",
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
        print(json.dumps({"error": f"Workflow file not found: {workflow_file}"}))
        sys.exit(1)

    try:
        flow_input = json.loads(args.json_input)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid --json-input: {e}"}))
        sys.exit(1)

    # Bootstrap environment before loading workflow (needs .env for API keys etc.)
    _bootstrap_environment()

    # Download HuggingFace models if a download script was bundled at publish time
    download_script = Path(__file__).parent / "download_models.py"
    if download_script.exists():
        result = subprocess.run(
            [sys.executable, str(download_script)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(json.dumps({"error": f"Model download failed: {result.stderr}"}))
            sys.exit(1)

    # Ensure the output directory exists before the workflow writes to it
    if args.output_dir:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    try:
        module = _load_workflow_module(str(workflow_file))
    except Exception as e:
        print(json.dumps({"error": f"Failed to load workflow: {e}"}))
        sys.exit(1)

    if not hasattr(module, "execute_workflow"):
        print(json.dumps({"error": "Workflow module has no execute_workflow() function"}))
        sys.exit(1)

    script_dir = Path(__file__).parent
    project_file = script_dir / "project.yml"

    try:
        output = module.execute_workflow(
            input=flow_input,
            storage_backend=args.storage_backend,
            project_file_path=str(project_file) if project_file.exists() else None,
        )
    except Exception as e:
        print(json.dumps({"error": f"Workflow execution failed: {e}"}), file=sys.stderr)
        sys.exit(1)

    macro_map = _build_macro_map(Path(__file__).parent)
    if args.output_dir:
        macro_map["outputs"] = args.output_dir
    result = _serialize_output(output, macro_map)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
