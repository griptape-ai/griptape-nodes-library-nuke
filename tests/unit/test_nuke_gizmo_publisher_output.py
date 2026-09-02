"""Tests for _customize_project_yml output filename macro, collision policy, and failure handling."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock
from unittest.mock import Mock

import pytest
from griptape_nodes.common.project_templates.default_project_template import DEFAULT_PROJECT_TEMPLATE
from griptape_nodes.common.project_templates.loader import load_project_template_from_yaml
from griptape_nodes.common.project_templates.situation import BuiltInSituation, SituationFilePolicy
from griptape_nodes.common.project_templates.validation import ProjectValidationInfo, ProjectValidationStatus
from griptape_nodes.retained_mode.events.os_events import (
    FileIOFailureReason,
    ReadFileRequest,
    ReadFileResultFailure,
    ReadFileResultSuccess,
    WriteFileRequest,
    WriteFileResultFailure,
    WriteFileResultSuccess,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.retained_mode.managers.project_manager import BUILTIN_VARIABLES

from publish_gizmo import nuke_gizmo_publisher
from publish_gizmo.nuke_gizmo_publisher import OUTPUTS_DIR_ENV_VAR, NukeGizmoPublisher

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from griptape_nodes.common.project_templates.project import ProjectTemplate


_KNOWN_SITUATIONS = frozenset(
    {
        "save_file",
        "copy_external_file",
        "download_url",
        "save_node_output",
        "save_griptape_nodes_preview",
        "save_static_file",
        "save_griptape_nodes_metadata",
        "save_workflow",
        "create_versioned_workflow",
        "save_workflow_thumbnail",
        "save_failed_workflow",
        "save_temp_file",
        "save_workflow_backup",
    }
)

_KNOWN_DIRECTORIES = frozenset(
    {
        "inputs",
        "outputs",
        "backups",
        "workflow_run_failures",
        "temp",
        "griptape-nodes-previews",
        "griptape-nodes-metadata",
        "griptape-nodes-thumbnails",
    }
)

_KNOWN_BUILTIN_VARIABLES = frozenset(
    {
        "project_dir",
        "project_name",
        "workspace_dir",
        "workflow_name",
        "workflow_dir",
        "static_files_dir",
    }
)

_KNOWN_SCHEMA_VERSION = "1.0.0"

_OVERRIDE_GUIDANCE = (
    "Decide whether the change needs an override in _customize_project_yml in "
    "publish_gizmo/nuke_gizmo_publisher.py: anything writable that resolves inside the installed "
    "gizmo bundle is a bug, because the bundle may be shared or read-only."
)


class TestCustomizeProjectYmlOutput:
    def test_fails_when_engine_adds_an_unhandled_situation(self) -> None:
        template_situations = set(DEFAULT_PROJECT_TEMPLATE.situations)
        assert _KNOWN_SITUATIONS == template_situations, (
            f"The default project template's situations changed. {_describe_delta(_KNOWN_SITUATIONS, template_situations)}\n"
            f"{_OVERRIDE_GUIDANCE}\n"
            "Then cover each added situation end to end: add a situation_<name> output parameter to "
            "CanaryNode in tests/integration/fixtures/canary/canary_library/canary_node.py, add the name to "
            "_MACRO_OUTPUTS in tests/integration/fixtures/canary/canary_workflow_builder.py, and assert its "
            "resolved path in test_default_macro_paths_resolution in tests/integration/test_canary_bundle.py.\n"
            "Once handled, update _KNOWN_SITUATIONS in this test."
        )

        enum_situations = {situation.value for situation in BuiltInSituation}
        assert _KNOWN_SITUATIONS == enum_situations, (
            f"BuiltInSituation changed. {_describe_delta(_KNOWN_SITUATIONS, enum_situations)}\n"
            "A new situation lands in the enum before the default project template names it, so it may not "
            f"be in the template yet.\n{_OVERRIDE_GUIDANCE}\n"
            "Then cover each added situation end to end: add a situation_<name> output parameter to "
            "CanaryNode in tests/integration/fixtures/canary/canary_library/canary_node.py, add the name to "
            "_MACRO_OUTPUTS in tests/integration/fixtures/canary/canary_workflow_builder.py, and assert its "
            "resolved path in test_default_macro_paths_resolution in tests/integration/test_canary_bundle.py.\n"
            "Once handled, update _KNOWN_SITUATIONS in this test."
        )

    def test_fails_when_engine_adds_an_unhandled_directory(self) -> None:
        template_directories = set(DEFAULT_PROJECT_TEMPLATE.directories)
        assert _KNOWN_DIRECTORIES == template_directories, (
            f"The default project template's directories changed. "
            f"{_describe_delta(_KNOWN_DIRECTORIES, template_directories)}\n"
            f"{_OVERRIDE_GUIDANCE}\n"
            "Once handled, update _KNOWN_DIRECTORIES in this test."
        )

    def test_fails_when_engine_adds_an_unhandled_builtin_macro_variable(self) -> None:
        assert _KNOWN_BUILTIN_VARIABLES == BUILTIN_VARIABLES, (
            f"The engine's built-in macro variables changed. "
            f"{_describe_delta(_KNOWN_BUILTIN_VARIABLES, BUILTIN_VARIABLES)}\n"
            "A path_macro the publisher leaves alone may now resolve somewhere new. "
            f"{_OVERRIDE_GUIDANCE}\n"
            "Once handled, update _KNOWN_BUILTIN_VARIABLES in this test."
        )

    def test_fails_when_the_default_project_template_schema_version_changes(self) -> None:
        actual = DEFAULT_PROJECT_TEMPLATE.project_template_schema_version
        assert actual == _KNOWN_SCHEMA_VERSION, (
            f"The default project template's schema version went from {_KNOWN_SCHEMA_VERSION!r} to {actual!r}.\n"
            "The situation and directory names this test guards can survive a schema bump unchanged while "
            "their meaning does not, so re-read the new schema and re-check every override in "
            "_customize_project_yml in publish_gizmo/nuke_gizmo_publisher.py.\n"
            "Once handled, update _KNOWN_SCHEMA_VERSION in this test."
        )

    def test_outputs_path_macro_references_outputs_dir_env_var(self, customized_template: ProjectTemplate) -> None:
        """Outputs must resolve to wherever the runner exported OUTPUTS_DIR_ENV_VAR, and nothing else."""
        actual = customized_template.directories["outputs"].path_macro
        assert actual == f"{{{OUTPUTS_DIR_ENV_VAR}}}", (
            f"Expected the outputs path_macro to be the plain single-token macro for OUTPUTS_DIR_ENV_VAR "
            f"({OUTPUTS_DIR_ENV_VAR!r}), with no optional-segment degradation, got: {actual!r}"
        )

    def test_save_node_output_macro_is_versioned(self, customized_template: ProjectTemplate) -> None:
        macro = customized_template.situations["save_node_output"].macro
        assert "{####?:^_v}" in macro, f"Expected versioned macro containing '{{####?:^_v}}', got: {macro!r}"

    def test_save_static_file_macro_leads_with_the_static_files_dir_token(
        self, customized_template: ProjectTemplate
    ) -> None:
        macro = customized_template.situations["save_static_file"].macro
        assert macro.startswith("{static_files_dir}"), (
            f"Expected the save_static_file macro to lead with the bare '{{static_files_dir}}' token, got: {macro!r}. "
            "Unlike the situations around it, this one carries no script-dir anchor and must not gain one: "
            "'static_files_dir' is registered is_directory=False, so it is interpolated verbatim and "
            "resolve_file_path hands it back unchanged -- the runner has already exported an absolute "
            "static_files_directory. Any prefix would produce a garbled, non-absolute string."
        )

    def test_save_node_output_collision_policy_is_create_new(self, customized_template: ProjectTemplate) -> None:
        on_collision = customized_template.situations["save_node_output"].policy.on_collision
        assert on_collision is SituationFilePolicy.CREATE_NEW, (
            f"Expected CREATE_NEW collision policy, got: {on_collision!r}"
        )


def _describe_delta(known: frozenset[str], actual: frozenset[str] | set[str]) -> str:
    """Name what the engine gained and lost since this test's known set was written."""
    parts = []
    added = sorted(actual - known)
    if added:
        parts.append(f"The engine added: {', '.join(added)}.")
    removed = sorted(known - actual)
    if removed:
        parts.append(f"The engine no longer has: {', '.join(removed)}.")
    return " ".join(parts)


# The publisher customizes the project.yml the engine's packager just wrote, so the
# engine's own default template is the realistic input here.
_BUNDLED_PROJECT_YML = DEFAULT_PROJECT_TEMPLATE.to_yaml()


def _read_success(content: str) -> ReadFileResultSuccess:
    return ReadFileResultSuccess(
        result_details="read",
        content=content,
        file_size=len(content),
        mime_type="text/yaml",
        encoding="utf-8",
        compression_encoding=None,
        is_text=True,
    )


class TestCustomizeProjectYmlFailures:
    """A rebuilt bundle has no earlier customized project.yml to fall back on.

    project.yml decides where a run's outputs land, so a bundle carrying the
    engine's un-customized template writes them inside the companion rather than
    next to the .nk file. Each of these paths used to return quietly.
    """

    def test_raises_when_project_yml_cannot_be_read(self, tmp_path) -> None:
        failure = ReadFileResultFailure(
            result_details="nope", exception=None, failure_reason=FileIOFailureReason.FILE_NOT_FOUND
        )
        with (
            mock.patch("publish_gizmo.nuke_gizmo_publisher.GriptapeNodes") as griptape_nodes,
            pytest.raises(TypeError, match="Failed to read the bundled project.yml"),
        ):
            griptape_nodes.handle_request.return_value = failure
            NukeGizmoPublisher._customize_project_yml(tmp_path)  # noqa: SLF001

    def test_raises_when_project_yml_cannot_be_parsed(self, tmp_path) -> None:
        with (
            mock.patch("publish_gizmo.nuke_gizmo_publisher.GriptapeNodes") as griptape_nodes,
            mock.patch("publish_gizmo.nuke_gizmo_publisher.load_project_template_from_yaml", return_value=None),
            pytest.raises(TypeError, match="Failed to parse the bundled project.yml"),
        ):
            griptape_nodes.handle_request.return_value = _read_success(_BUNDLED_PROJECT_YML)
            NukeGizmoPublisher._customize_project_yml(tmp_path)  # noqa: SLF001

    def test_raises_when_customized_project_yml_cannot_be_written(self, tmp_path) -> None:
        def _handle(request):  # noqa: ANN001, ANN202
            if isinstance(request, ReadFileRequest):
                return _read_success(_BUNDLED_PROJECT_YML)
            if isinstance(request, WriteFileRequest):
                return WriteFileResultFailure(
                    result_details="nope",
                    exception=None,
                    failure_reason=FileIOFailureReason.PERMISSION_DENIED,
                    missing_variables=None,
                )
            msg = f"unexpected request: {type(request).__name__}"
            raise AssertionError(msg)

        with (
            mock.patch("publish_gizmo.nuke_gizmo_publisher.GriptapeNodes") as griptape_nodes,
            pytest.raises(TypeError, match="Failed to write the customized project.yml"),
        ):
            griptape_nodes.handle_request.side_effect = _handle
            NukeGizmoPublisher._customize_project_yml(tmp_path)  # noqa: SLF001

    def test_writes_the_customized_template_on_the_happy_path(self, tmp_path) -> None:
        written: list[str] = []

        def _handle(request):  # noqa: ANN001, ANN202
            if isinstance(request, ReadFileRequest):
                return _read_success(_BUNDLED_PROJECT_YML)
            if isinstance(request, WriteFileRequest):
                written.append(str(request.content))
                return WriteFileResultSuccess(
                    result_details="written", final_file_path=str(request.file_path), bytes_written=1
                )
            msg = f"unexpected request: {type(request).__name__}"
            raise AssertionError(msg)

        with mock.patch("publish_gizmo.nuke_gizmo_publisher.GriptapeNodes") as griptape_nodes:
            griptape_nodes.handle_request.side_effect = _handle
            NukeGizmoPublisher._customize_project_yml(tmp_path)  # noqa: SLF001

        assert len(written) == 1
        # The outputs directory is redirected through the runner's env var rather than a
        # literal folder name, so the macro -- not "griptape_outputs" -- is what lands here.
        assert "GTN_NUKE_GIZMO_OUTPUTS_DIR" in written[0]
        assert "save_node_output" in written[0]


# The writeable directories the customized project.yml must anchor on the runner's
# script-dir variable, and the path_macro each must carry.
_SCRIPT_ANCHORED_DIRECTORY_MACROS = {
    "backups": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/backups",
    "workflow_run_failures": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/workflow_run_failures",
    "temp": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/temp",
    "griptape-nodes-previews": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/previews",
    "griptape-nodes-metadata": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/metadata",
    "griptape-nodes-thumbnails": "{GTN_NUKE_GIZMO_SCRIPT_DIR}/.griptape/thumbnails",
}

# Stands in for a directory the customized project.yml never defined, so a name that went missing
# fails as a readable diff rather than a KeyError.
_MISSING_DIRECTORY = "<absent from the customized project.yml>"


class TestCustomizeProjectYmlDirectories:
    """The bundle's directories must be writable, and its bundled assets readable, wherever the gizmo is installed."""

    def test_writable_directories_anchor_on_the_script_dir_variable(self, customized_template: ProjectTemplate) -> None:
        """Each of these directories is gathered under a hidden parent, hung off the runner's anchor.

        Left as the packager wrote them, all but ``griptape-nodes-thumbnails`` default to
        ``{workflow_dir?:/}<name>``; that one defaults to a bare ``.griptape-nodes-thumbnails``,
        which the engine anchors on ``workspace_path`` -- pinned by the runner to the bundle root.
        Either way they resolve inside the installed gizmo, a location that may be shared or
        read-only.
        """
        directories = customized_template.directories
        actual = {
            name: directories[name].path_macro if name in directories else _MISSING_DIRECTORY
            for name in _SCRIPT_ANCHORED_DIRECTORY_MACROS
        }
        assert actual == _SCRIPT_ANCHORED_DIRECTORY_MACROS

    def test_outputs_still_resolves_through_the_outputs_dir_variable(
        self, customized_template: ProjectTemplate
    ) -> None:
        """``outputs`` follows the Output Directory knob, so it keeps its own variable, not the anchor."""
        assert customized_template.directories["outputs"].path_macro == "{GTN_NUKE_GIZMO_OUTPUTS_DIR}"

    def test_inputs_anchors_on_the_bundle_root(self, customized_template: ProjectTemplate) -> None:
        """``inputs`` goes the opposite way to the writable directories: inside the bundle, not beside the .nk.

        The packager copies the assets bundled at publish time to ``<bundle>/inputs``, under the
        bundle root the runner pins ``{workspace_dir}`` to, so that is where a run has to look for
        them. See ``_customize_project_yml`` for why the packager's own default lands somewhere else.
        """
        definition = customized_template.directories.get("inputs")
        actual = definition.path_macro if definition is not None else _MISSING_DIRECTORY
        assert actual == "{workspace_dir}/inputs"


@pytest.fixture
def customized_template(customize_project_yml: Callable[[Path], ProjectTemplate], tmp_path: Path) -> ProjectTemplate:
    """The customized template, for a test that has no interest in the companion directory."""
    return customize_project_yml(tmp_path)


@pytest.fixture
def customize_project_yml(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path], ProjectTemplate]:
    """Runs _customize_project_yml over the engine's default template and parses what it wrote back."""

    def _customize(companion_base: Path) -> ProjectTemplate:
        mock_engine = Mock(spec=GriptapeNodes)
        mock_engine.handle_request.side_effect = [
            _read_success(_BUNDLED_PROJECT_YML),
            WriteFileResultSuccess(
                result_details="written",
                final_file_path=str(companion_base / "project.yml"),
                bytes_written=1,
            ),
        ]
        monkeypatch.setattr(nuke_gizmo_publisher, "GriptapeNodes", mock_engine)

        NukeGizmoPublisher._customize_project_yml(companion_base)  # noqa: SLF001

        assert mock_engine.handle_request.call_count == 2, (
            f"Expected _customize_project_yml to make exactly two engine requests, a read then a write, "
            f"got: {mock_engine.handle_request.call_args_list}"
        )
        written = str(mock_engine.handle_request.call_args_list[1].args[0].content)
        validation_info = ProjectValidationInfo(status=ProjectValidationStatus.GOOD)
        template = load_project_template_from_yaml(written, validation_info)
        assert template is not None, f"Could not parse the customized project.yml:\n{written}"
        return template

    return _customize
