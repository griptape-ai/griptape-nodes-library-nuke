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
import sys
from pathlib import Path

from dotenv import load_dotenv


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


def _serialize_output(output: dict | None) -> dict[str, str]:
    """Flatten and serialize the workflow output dict for JSON printing.

    The executor returns a nested dict: {node_name: {param_name: value}}.
    We flatten it to {param_name: str(value)} for the gizmo to consume.
    Image artifacts expose a .url or .value attribute that contains the path.
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
                result[param_name] = url
            elif hasattr(value, "value") and isinstance(getattr(value, "value"), (str, bytes)):
                raw = value.value
                if isinstance(raw, bytes):
                    result[param_name] = f"<binary {len(raw)} bytes>"
                else:
                    result[param_name] = raw
            else:
                result[param_name] = str(value)

    return result


def main() -> None:
    logging.basicConfig(level=logging.WARNING)

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

    try:
        module = _load_workflow_module(str(workflow_file))
    except Exception as e:
        print(json.dumps({"error": f"Failed to load workflow: {e}"}))
        sys.exit(1)

    if not hasattr(module, "execute_workflow"):
        print(json.dumps({"error": "Workflow module has no execute_workflow() function"}))
        sys.exit(1)

    try:
        output = module.execute_workflow(
            input=flow_input,
            storage_backend=args.storage_backend,
            project_file_path=args.output_dir,
        )
    except Exception as e:
        print(json.dumps({"error": f"Workflow execution failed: {e}"}), file=sys.stderr)
        sys.exit(1)

    result = _serialize_output(output)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
