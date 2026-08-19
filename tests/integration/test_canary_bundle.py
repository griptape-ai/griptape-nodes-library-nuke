"""The gizmo runner must not repoint ``workspace_path`` at the .nk dir.

This is the no-Nuke bundle-level test: no Nuke required. Publishes a real bundle
in-process, then invokes the bundle's ``run_workflow.py`` exactly as ``run_button.py``
would (a ``sys.executable`` subprocess, no ``uv run``), and inspects the reported
output plus the actual files written to disk.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# The module the publisher copies into every bundle as run_workflow.py, imported flat exactly as
# the bundle imports it. See tests/conftest.py for the XDG_CONFIG_HOME guard this import relies on.
import nuke_workflow_runner
from griptape_nodes.common.project_templates import load_project_template_from_yaml
from griptape_nodes.common.project_templates.validation import ProjectValidationInfo, ProjectValidationStatus

from publish_gizmo.output_protocol import extract_payload

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest
    from griptape_nodes.common.project_templates.project import ProjectTemplate

    from .fixtures.canary.canary_workflow_builder import PublishedBundle

# Invented, non-secret, and placed in the bundle subprocess's environment by one test alone, so
# finding it in a payload can only mean the environment was read.
_SENTINEL_VALUE = "sentinel-must-not-appear-in-output"

# Invented, non-secret, and a legal directory name: the Output Directory knob deliberately does
# resolve an environment variable, so this one has to be usable as a folder.
_OUTDIR_SENTINEL_VALUE = "gtn-canary-envdir"

# Names nothing at all: not a project directory, not a builtin, and put in no environment by any
# test here, so the engine has no way to resolve it and every route to a value is closed off.
_UNRESOLVABLE_NAME = "GTN_NUKE_CANARY_NOPE"

# The file name CanaryNode hands to CreateStaticFileRequest.
_CANARY_STATIC_FILE_NAME = "canary_created_static.txt"

# Every writable directory in the bundle's project.yml.
_SCRIPT_ANCHORED_DIRECTORY_MACROS = {
    "backups": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/backups",
    "workflow_run_failures": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/workflow_run_failures",
    "temp": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/temp",
    "griptape-nodes-previews": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/previews",
    "griptape-nodes-metadata": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/metadata",
    "griptape-nodes-thumbnails": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/thumbnails",
}

# Directory name -> the CanaryNode output parameter reporting where it resolved to. Each of these
# names is a key of ``template.directories``, so the engine genuinely computes it: a run that
# reported the raw ``{name}`` back would mean nothing resolved it at all.
_DIRECTORY_OUTPUT_PARAMETERS = {
    "backups": "backups_dir",
    "workflow_run_failures": "workflow_run_failures_dir",
    "temp": "temp_dir",
    "griptape-nodes-previews": "previews_dir",
    "griptape-nodes-metadata": "metadata_dir",
    "griptape-nodes-thumbnails": "thumbnails_dir",
}

# The one macro directory the publisher anchors INSIDE the bundle, likely to contain
# node dependencies bundled at publish time, and not expected to be written to during
# execution.
_BUNDLE_ANCHORED_DIRECTORY = "inputs"
_BUNDLE_ANCHORED_DIRECTORY_MACRO = "{workspace_dir}/inputs"

# Stands in for a directory the published project.yml never defined, so a name that went missing
# fails as a readable diff rather than a KeyError.
_MISSING_DIRECTORY = "<absent from the published project.yml>"


def _run_bundle(
    bundle: PublishedBundle,
    nk_dir: Path,
    env: dict[str, str],
    *,
    json_input: str = "{}",
    output_dir: str | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(bundle.companion_base / "run_workflow.py"),
        "--workflow-file",
        str(bundle.workflow_file),
        "--json-input",
        json_input,
        "--nk-script-dir",
        str(nk_dir),
    ]
    if output_dir is not None:
        cmd.extend(["--output-dir", output_dir])
    return subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(bundle.companion_base),
        timeout=120,
        check=False,
    )


def test_default_macro_paths_resolution(
    published_bundle: Callable[..., PublishedBundle],
    engine_subprocess_env: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> None:
    """The Canary node exports many macros in parameters, which we expect to be expanded"""
    bundle = published_bundle()
    nk_dir = tmp_path / "nk_shot"
    nk_dir.mkdir()

    result = _run_bundle(bundle, nk_dir, engine_subprocess_env(GTN_NUKE_CANARY_SENTINEL=_SENTINEL_VALUE))

    diagnostic = f"exit={result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    assert result.returncode == 0, diagnostic  # Fails e.g. if static file is not bundled.

    payload = extract_payload(result.stdout)

    # Check the expected output file is written to the expected location.
    reported_output_file_path = Path(payload["output_path"])
    assert reported_output_file_path.is_absolute(), diagnostic
    assert reported_output_file_path.is_file(), diagnostic
    expected_output_file_path = nk_dir / "griptape_outputs" / "canary_output.txt"
    assert reported_output_file_path == expected_output_file_path, diagnostic
    assert not (bundle.companion_base / "griptape_outputs").exists(), diagnostic

    # Check the same path bundled through an ImageUrlArtifact is written to the same location.
    reported_output_artifact_path = Path(payload["image_url_artifact"])
    assert reported_output_artifact_path == expected_output_file_path, diagnostic

    # Check workflow dir matches the versioned directory in the bundle.
    reported_workflow_dir = Path(payload["workflow_dir"])
    assert reported_workflow_dir.is_absolute(), diagnostic
    assert reported_workflow_dir.is_dir(), diagnostic
    assert reported_workflow_dir.parent.samefile(bundle.companion_base), diagnostic
    assert re.fullmatch(r"v\d+", reported_workflow_dir.name), diagnostic

    # Check workspace dir matches the bundle's companion base.
    reported_workspace_dir = Path(payload["workspace_dir"])
    assert reported_workspace_dir.is_absolute(), diagnostic
    assert reported_workspace_dir.samefile(bundle.companion_base), diagnostic

    # Check project dir matches the bundle's companion base.
    reported_project_dir = Path(payload["project_dir"])
    assert reported_project_dir.is_absolute(), diagnostic
    assert reported_project_dir.samefile(bundle.companion_base), diagnostic

    # Check env vars are not substituted (confidence check of standard engine behaviour
    # for output parameters).
    assert payload["env_sentinel"] == "{GTN_NUKE_CANARY_SENTINEL}", diagnostic

    # Check {inputs}-anchored file dependency is resolved to the expected path
    reported_static_file_path = Path(payload["static_file_path"])
    expected_static_file_path = bundle.companion_base / "assets" / "canary_asset.txt"
    assert reported_static_file_path == expected_static_file_path, diagnostic

    # Check {statics}-anchored file dependency is resolved to the expected path
    reported_macro_static_file_path = Path(payload["macro_static_file_path"])
    expected_macro_static_file_path = bundle.companion_base / "inputs" / "canary_macro_asset.txt"
    assert reported_macro_static_file_path == expected_macro_static_file_path, diagnostic

    # Check the built-in situations that land beside the .nk script, where a run's writes belong.
    assert Path(payload["situation_save_node_output"]) == nk_dir / "griptape_outputs" / "canary_file_v0001.txt", (
        diagnostic
    )
    griptape_dir = nk_dir / ".griptape"
    assert Path(payload["situation_save_temp_file"]) == griptape_dir / "temp" / "canary_file.txt", diagnostic
    assert (
        Path(payload["situation_save_workflow_backup"]) == griptape_dir / "backups" / "canary_file_backup_v001.txt"
    ), diagnostic
    assert (
        Path(payload["situation_save_failed_workflow"])
        == griptape_dir / "workflow_run_failures" / "canary_file_run_001.txt"
    ), diagnostic
    assert (
        Path(payload["situation_save_griptape_nodes_preview"]) == griptape_dir / "previews" / "canary_file.txt.png"
    ), diagnostic
    assert (
        Path(payload["situation_save_griptape_nodes_metadata"]) == griptape_dir / "metadata" / "canary_file.txt.json"
    ), diagnostic
    assert Path(payload["situation_save_workflow_thumbnail"]) == griptape_dir / "thumbnails" / "canary_file.txt", (
        diagnostic
    )
    assert Path(payload["situation_save_file"]) == griptape_dir / "canary_file.txt", diagnostic
    assert Path(payload["situation_save_workflow"]) == griptape_dir / "canary_file.txt", diagnostic
    assert Path(payload["situation_create_versioned_workflow"]) == griptape_dir / "canary_file.txt", diagnostic
    assert Path(payload["situation_copy_external_file"]) == griptape_dir / "inputs" / "text" / "canary_file.txt", (
        diagnostic
    )
    assert Path(payload["situation_download_url"]) == griptape_dir / "inputs" / "text" / "canary_file.txt", diagnostic
    assert Path(payload["situation_save_static_file"]) == griptape_dir / "staticfiles" / "canary_file.txt", diagnostic


def test_outputs_macro_resolves_when_bundle_project_has_a_real_id(
    published_bundle: Callable[..., PublishedBundle],
    engine_subprocess_env: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> None:
    """A ``--output-dir`` containing a macro must resolve to a path beside the .nk script.

    The bundle is published with an explicit project id because that is what a real one carries:
    ``ProjectTemplate.id`` is a GUID the UI sets on every project it creates. The other tests
    publish against system defaults, which declare no id, so they cover only the legacy
    path-derived fallback.
    """
    bundle = published_bundle(project_id="canary-fixed-project-id")
    assert "canary-fixed-project-id" in (bundle.companion_base / "project.yml").read_text(), (
        "The published bundle's project.yml must carry the fixed project id; otherwise this test "
        "exercises no id collision at all."
    )
    nk_dir = tmp_path / "nk_shot"
    nk_dir.mkdir()

    result = _run_bundle(bundle, nk_dir, engine_subprocess_env(), output_dir="{outputs}/renders")

    diagnostic = f"exit={result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    assert result.returncode == 0, diagnostic

    payload = extract_payload(result.stdout)
    reported_output_file_path = Path(payload["output_path"])
    assert reported_output_file_path.is_absolute(), diagnostic
    assert reported_output_file_path.is_file(), diagnostic
    expected_output_file_path = nk_dir / "griptape_outputs" / "renders" / "canary_output.txt"
    assert reported_output_file_path == expected_output_file_path, diagnostic


def test_output_dir_knob_may_contain_builtin_and_environment_variables(
    published_bundle: Callable[..., PublishedBundle],
    engine_subprocess_env: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> None:
    """An Output Directory naming a builtin project variable or an environment variable must resolve it."""
    bundle = published_bundle()
    nk_dir = tmp_path / "nk_shot"
    nk_dir.mkdir()

    env = engine_subprocess_env(GTN_NUKE_CANARY_OUTDIR=_OUTDIR_SENTINEL_VALUE)
    result = _run_bundle(bundle, nk_dir, env, output_dir="{project_dir}/{GTN_NUKE_CANARY_OUTDIR}/renders")

    diagnostic = f"exit={result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    assert result.returncode == 0, diagnostic

    payload = extract_payload(result.stdout)
    reported_output_file_path = Path(payload["output_path"])
    assert reported_output_file_path.is_absolute(), diagnostic
    assert reported_output_file_path.is_file(), diagnostic
    expected_output_file_path = bundle.companion_base / _OUTDIR_SENTINEL_VALUE / "renders" / "canary_output.txt"
    assert reported_output_file_path == expected_output_file_path, diagnostic


def test_output_dir_knob_relative_paths_are_anchored_on_nk_script(
    published_bundle: Callable[..., PublishedBundle],
    engine_subprocess_env: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> None:
    """An Output Directory containing a relative path must have the path anchored on the Nuke script directory."""
    bundle = published_bundle()
    nk_dir = tmp_path / "nk_shot"
    nk_dir.mkdir()

    env = engine_subprocess_env()
    result = _run_bundle(bundle, nk_dir, env, output_dir="renders")

    diagnostic = f"exit={result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    assert result.returncode == 0, diagnostic

    payload = extract_payload(result.stdout)
    reported_output_file_path = Path(payload["output_path"])
    assert reported_output_file_path.is_absolute(), diagnostic
    assert reported_output_file_path.is_file(), diagnostic
    expected_output_file_path = nk_dir / "renders" / "canary_output.txt"
    assert reported_output_file_path == expected_output_file_path, diagnostic


def test_output_dir_knob_with_unknown_macro_fails_the_run_early(
    published_bundle: Callable[..., PublishedBundle],
    engine_subprocess_env: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> None:
    """One unresolvable macro name in Output Directory aborts the whole run."""
    bundle = published_bundle()
    nk_dir = tmp_path / "nk_shot"
    nk_dir.mkdir()

    env = engine_subprocess_env()
    assert _UNRESOLVABLE_NAME not in env, (
        f"{_UNRESOLVABLE_NAME} reached the bundle subprocess's environment, so the engine could "
        "resolve it and this test would pin nothing."
    )
    output_dir = f"{{outputs}}/{{{_UNRESOLVABLE_NAME}}}"

    result = _run_bundle(bundle, nk_dir, env, output_dir=output_dir)

    diagnostic = f"exit={result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    # Fails in the engine during execution, when it tries to resolve the unresolvable.
    assert result.returncode != 0, diagnostic

    # The artist is told which name failed and shown the text they typed, not an engine internal.
    error = extract_payload(result.stdout)["error"]
    assert _UNRESOLVABLE_NAME in error, diagnostic
    assert output_dir in error, diagnostic
    assert "FileLoadError" not in error, diagnostic

    # Nothing on disk: not the literal folder the anchored text used to produce, not the default
    # outputs directory the resolvable half would have produced, not a stray file anywhere else.
    assert list(nk_dir.rglob("*")) == [], diagnostic


def test_multiple_runs_create_versioned_outputs(
    published_bundle: Callable[..., PublishedBundle],
    engine_subprocess_env: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> None:
    """An Output Directory containing a relative path must have the path anchored on the Nuke script directory."""
    bundle = published_bundle()
    nk_dir = tmp_path / "nk_shot"
    nk_dir.mkdir()

    env = engine_subprocess_env()

    def assert_result(result: subprocess.CompletedProcess[str], expected_filename: Path) -> None:
        diagnostic = f"exit={result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        assert result.returncode == 0, diagnostic

        payload = extract_payload(result.stdout)
        reported_output_file_path = Path(payload["output_path"])
        assert reported_output_file_path.is_absolute(), diagnostic
        assert reported_output_file_path.is_file(), diagnostic
        expected_output_file_path = nk_dir / "griptape_outputs" / expected_filename
        assert reported_output_file_path == expected_output_file_path, diagnostic

    result = _run_bundle(bundle, nk_dir, env)
    assert_result(result, Path("canary_output.txt"))
    result = _run_bundle(bundle, nk_dir, env)
    assert_result(result, Path("canary_output_v0001.txt"))
    result = _run_bundle(bundle, nk_dir, env)
    assert_result(result, Path("canary_output_v0002.txt"))


def test_writable_directories_resolve_beside_the_nk_script(
    published_bundle: Callable[..., PublishedBundle],
    engine_subprocess_env: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> None:
    """Every writable directory the engine computes must land beside the .nk script, not in the bundle."""
    bundle = published_bundle()
    nk_dir = tmp_path / "nk_shot"
    nk_dir.mkdir()

    result = _run_bundle(bundle, nk_dir, engine_subprocess_env())

    diagnostic = f"exit={result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    assert result.returncode == 0, diagnostic
    payload = extract_payload(result.stdout)

    for directory_name, parameter_name in _DIRECTORY_OUTPUT_PARAMETERS.items():
        reported = payload[parameter_name]
        assert "{" not in reported, (
            f"'{directory_name}' came back as unresolved text {reported!r}, so this test would pin "
            f"nothing about where it lands.\n{diagnostic}"
        )
        resolved = Path(reported)
        assert resolved.is_absolute(), f"'{directory_name}' -> {reported!r}\n{diagnostic}"
        assert resolved.resolve().is_relative_to(nk_dir.resolve()), (
            f"'{directory_name}' resolved to {reported!r}, outside the .nk script directory {nk_dir}.\n{diagnostic}"
        )
        assert not resolved.resolve().is_relative_to(bundle.companion_base.resolve()), (
            f"'{directory_name}' resolved to {reported!r}, inside the installed bundle.\n{diagnostic}"
        )

    # A static file is the one writable location project.yml alone cannot move: the engine takes
    # it from the `static_files_directory` config value, so this proves the runner's override lands.
    url = payload["created_static_file_url"]
    match = re.fullmatch(rf"http://[^/]+/external/(?P<path>.+/{re.escape(_CANARY_STATIC_FILE_NAME)})\?t=\d+", url)
    assert match is not None, f"Static file URL {url!r} is not a well-formed external static URL.\n{diagnostic}"

    written = Path("/" + match.group("path"))
    assert written.is_file(), f"Static file URL {url!r} names no file on disk.\n{diagnostic}"
    assert written.resolve().is_relative_to((nk_dir / ".griptape" / "staticfiles").resolve()), (
        f"Static file was written to {written}, not beside the .nk script.\n{diagnostic}"
    )
    assert not written.resolve().is_relative_to(bundle.companion_base.resolve()), (
        f"Static file was written to {written}, inside the installed bundle.\n{diagnostic}"
    )


def test_synced_workflows_scratch_lands_in_the_per_machine_data_directory(
    published_bundle: Callable[..., PublishedBundle],
    engine_subprocess_env: Callable[..., dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cloud-sync scratch directory must be created under XDG_DATA_HOME, not in the bundle."""
    bundle = published_bundle()
    nk_dir = tmp_path / "nk_shot"
    nk_dir.mkdir()
    env = engine_subprocess_env()

    # The runner reads XDG_DATA_HOME from its own environment, so mirroring the subprocess's value
    # here derives the expected path from the shipped code rather than restating it.
    monkeypatch.setenv("XDG_DATA_HOME", env["XDG_DATA_HOME"])
    expected_synced_workflows = Path(nuke_workflow_runner._per_machine_synced_workflows_dir())
    assert expected_synced_workflows.is_relative_to(tmp_path), (
        f"The expected scratch path {expected_synced_workflows} is outside the test's tmp_path, so "
        "this test would inspect (and the run would write to) the developer's own home directory."
    )

    result = _run_bundle(bundle, nk_dir, env)

    diagnostic = f"exit={result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    assert result.returncode == 0, diagnostic

    # SyncManager mkdir's this unguarded during Engine.__init__, so a run always creates it
    # somewhere; only a positive assertion pins down where.
    assert expected_synced_workflows.is_dir(), diagnostic
    assert list(bundle.companion_base.rglob("synced_workflows")) == [], diagnostic


def test_bundle_project_yml_anchors_writable_directories_on_the_nk_script_dir(
    published_bundle: Callable[..., PublishedBundle],
) -> None:
    """Each writable directory is gathered under a hidden parent, hung off the runner's script-dir anchor."""
    bundle = published_bundle()
    project_yml = bundle.companion_base / "project.yml"

    template = _load_project_template(project_yml)
    assert template is not None, f"Could not parse the published bundle's project.yml at {project_yml}."

    actual = {
        name: template.directories[name].path_macro if name in template.directories else _MISSING_DIRECTORY
        for name in _SCRIPT_ANCHORED_DIRECTORY_MACROS
    }
    assert actual == _SCRIPT_ANCHORED_DIRECTORY_MACROS


def test_bundle_project_yml_anchors_inputs_on_the_bundle_root(
    published_bundle: Callable[..., PublishedBundle],
) -> None:
    """``inputs`` must resolve inside the bundle, the one directory that does."""
    bundle = published_bundle()
    project_yml = bundle.companion_base / "project.yml"

    template = _load_project_template(project_yml)
    assert template is not None, f"Could not parse the published bundle's project.yml at {project_yml}."

    definition = template.directories.get(_BUNDLE_ANCHORED_DIRECTORY)
    actual = definition.path_macro if definition is not None else _MISSING_DIRECTORY
    assert actual == _BUNDLE_ANCHORED_DIRECTORY_MACRO


def test_bundle_project_yml_resolves_inside_the_bundle_for_reads_only(
    published_bundle: Callable[..., PublishedBundle],
) -> None:
    """Directories other than ``inputs`` in project.yml must not resolve inside the gizmo."""
    bundle = published_bundle()
    project_yml = bundle.companion_base / "project.yml"
    raw_text = project_yml.read_text(encoding="utf-8")

    template = _load_project_template(project_yml)
    assert template is not None, f"Could not parse the published bundle's project.yml at {project_yml}."

    problems = []
    if "{project_dir}" in raw_text:
        problems.append(
            "contains a literal '{project_dir}' macro, which always resolves to the bundle's own "
            "directory and would bypass the OUTPUTS_DIR_ENV_VAR indirection outputs rely on."
        )

    anchored = {}
    for directory_name, definition in template.directories.items():
        path_macro = definition.path_macro
        if not isinstance(path_macro, str):
            continue
        if any(builtin in path_macro for builtin in ("{workflow_dir", "{workspace_dir", "{project_dir")):
            anchored[directory_name] = path_macro

    problems.extend(
        f"anchors its '{directory_name}' directory on the bundle via path_macro={path_macro!r}, "
        "so the engine would write into the installed gizmo rather than beside the .nk script."
        for directory_name, path_macro in anchored.items()
        if directory_name != _BUNDLE_ANCHORED_DIRECTORY
    )
    if _BUNDLE_ANCHORED_DIRECTORY not in anchored:
        definition = template.directories.get(_BUNDLE_ANCHORED_DIRECTORY)
        found = f"path_macro={definition.path_macro!r}" if definition is not None else "the directory is absent"
        problems.append(
            f"does NOT anchor its '{_BUNDLE_ANCHORED_DIRECTORY}' directory on the bundle ({found}), so a run "
            "would look for the assets the packager bundled somewhere they were never copied."
        )
    if template.parent_project_path is not None:
        problems.append(
            f"declares parent_project_path={template.parent_project_path!r}, which may not exist once "
            "this bundle is copied to a different machine or install location."
        )
    if template.parent_project_id is not None:
        problems.append(
            f"declares parent_project_id={template.parent_project_id!r}, which may not exist once "
            "this bundle is copied to a different machine or install location."
        )

    assert not problems, (
        f"The published bundle's project.yml at {project_yml} " + "; also ".join(problems) + ". "
        "See this test's own docstring for why each of these constructs is unsafe in a "
        "bundle's project.yml."
    )


def _load_project_template(project_yml: Path) -> ProjectTemplate | None:
    """Load a project.yml into a template, or None if it is missing.

    Lives here rather than in output_paths, which is copied verbatim into every artist's
    gizmo bundle: nothing at runtime parses a project.yml itself.
    """
    if not project_yml.exists():
        return None
    validation_info = ProjectValidationInfo(status=ProjectValidationStatus.GOOD)
    return load_project_template_from_yaml(project_yml.read_text(encoding="utf-8"), validation_info)
