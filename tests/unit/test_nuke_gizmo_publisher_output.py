"""Tests for _customize_project_yml output filename macro, collision policy, and failure handling."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest import mock

import pytest
from griptape_nodes.common.project_templates.default_project_template import DEFAULT_PROJECT_TEMPLATE
from griptape_nodes.retained_mode.events.os_events import (
    FileIOFailureReason,
    ReadFileRequest,
    ReadFileResultFailure,
    ReadFileResultSuccess,
    WriteFileRequest,
    WriteFileResultFailure,
    WriteFileResultSuccess,
)

from publish_gizmo.nuke_gizmo_publisher import NukeGizmoPublisher

_PUBLISHER = Path(__file__).parent.parent.parent / "publish_gizmo" / "nuke_gizmo_publisher.py"


def _get_customize_project_yml_source() -> ast.FunctionDef:
    src = _PUBLISHER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_customize_project_yml":
            return node
    msg = "_customize_project_yml not found in nuke_gizmo_publisher.py"
    raise AssertionError(msg)


def _find_situation_template_call(func: ast.FunctionDef) -> ast.Call:
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            func_node = node.func
            if isinstance(func_node, ast.Name) and func_node.id == "SituationTemplate":
                return node
            if isinstance(func_node, ast.Attribute) and func_node.attr == "SituationTemplate":
                return node
    msg = "SituationTemplate() call not found in _customize_project_yml"
    raise AssertionError(msg)


def _get_keyword_value(call: ast.Call, name: str) -> ast.expr:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    msg = f"keyword '{name}' not found in call {ast.dump(call.func)}"
    raise AssertionError(msg)


def _find_directory_definition_call(func: ast.FunctionDef, *, name: str) -> ast.Call:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        func_node = node.func
        is_directory_definition = (isinstance(func_node, ast.Name) and func_node.id == "DirectoryDefinition") or (
            isinstance(func_node, ast.Attribute) and func_node.attr == "DirectoryDefinition"
        )
        if not is_directory_definition:
            continue
        name_value = _get_keyword_value(node, "name")
        if isinstance(name_value, ast.Constant) and name_value.value == name:
            return node
    msg = f"DirectoryDefinition(name={name!r}, ...) call not found in _customize_project_yml"
    raise AssertionError(msg)


class TestCustomizeProjectYmlOutput:
    def test_outputs_path_macro_references_outputs_dir_env_var(self) -> None:
        """Outputs must resolve to wherever the runner exported OUTPUTS_DIR_ENV_VAR, and nothing else."""
        func = _get_customize_project_yml_source()
        call = _find_directory_definition_call(func, name="outputs")
        path_macro_source = ast.unparse(_get_keyword_value(call, "path_macro"))
        assert "OUTPUTS_DIR_ENV_VAR" in path_macro_source, (
            f"Expected the outputs path_macro to reference OUTPUTS_DIR_ENV_VAR, got: {path_macro_source!r}"
        )
        assert "?:/" not in path_macro_source, (
            f"Expected a plain single-token macro (no optional-segment degradation), got: {path_macro_source!r}"
        )

    def test_save_node_output_macro_is_versioned(self) -> None:
        func = _get_customize_project_yml_source()
        call = _find_situation_template_call(func)
        macro_node = _get_keyword_value(call, "macro")
        assert isinstance(macro_node, ast.Constant)
        assert isinstance(macro_node.value, str)
        assert "{####?:^_v}" in macro_node.value, (
            f"Expected versioned macro containing '{{####?:^_v}}', got: {macro_node.value!r}"
        )

    def test_save_node_output_collision_policy_is_create_new(self) -> None:
        func = _get_customize_project_yml_source()
        call = _find_situation_template_call(func)
        policy_node = _get_keyword_value(call, "policy")

        # Find the SituationPolicy(...) call and its on_collision keyword
        assert isinstance(policy_node, ast.Call)
        on_collision_node = _get_keyword_value(policy_node, "on_collision")

        # Must be SituationFilePolicy.CREATE_NEW
        assert isinstance(on_collision_node, ast.Attribute), (
            f"Expected an attribute access, got {ast.dump(on_collision_node)}"
        )
        assert on_collision_node.attr == "CREATE_NEW", (
            f"Expected CREATE_NEW collision policy, got: {on_collision_node.attr!r}"
        )


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
