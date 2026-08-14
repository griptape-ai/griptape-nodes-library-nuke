"""Tests for output_paths — Output Directory resolution and macro-path serialization."""

from __future__ import annotations

from pathlib import Path

from griptape_nodes.common.project_templates.directory import DirectoryDefinition
from griptape_nodes.common.project_templates.project import ProjectTemplate

from publish_gizmo.output_paths import (
    build_macro_map,
    resolve_macro_path,
    resolve_output_dir,
    serialize_output,
)

_NK_DIR = "/projects/shot_010/comp"
_COMPANION = "/library/griptape/my_workflow"


class _FakeUrlArtifact:
    def __init__(self, url: str) -> None:
        self.url = url


class _FakeValueArtifact:
    def __init__(self, value: str | bytes) -> None:
        self.value = value


class TestResolveOutputDir:
    def test_blank_dir_returns_none(self) -> None:
        assert resolve_output_dir(None, _NK_DIR, _COMPANION) is None
        assert resolve_output_dir("", _NK_DIR, _COMPANION) is None

    def test_relative_dir_resolves_against_nk_script_dir(self) -> None:
        assert resolve_output_dir("flibbidy", _NK_DIR, _COMPANION) == f"{_NK_DIR}/flibbidy"

    def test_relative_dir_falls_back_to_companion_when_script_unsaved(self) -> None:
        assert resolve_output_dir("flibbidy", None, _COMPANION) == f"{_COMPANION}/flibbidy"

    def test_absolute_dir_is_returned_normalized(self) -> None:
        assert resolve_output_dir("/renders/./out/", _NK_DIR, _COMPANION) == "/renders/out"

    def test_windows_backslashes_become_forward_slashes(self) -> None:
        assert resolve_output_dir("renders\\v001", _NK_DIR, _COMPANION) == f"{_NK_DIR}/renders/v001"

    def test_tilde_is_expanded_to_home(self) -> None:
        expected = str(Path.home() / "renders").replace("\\", "/")
        assert resolve_output_dir("~/renders", _NK_DIR, _COMPANION) == expected

    def test_engine_macro_value_is_passed_through_unchanged(self) -> None:
        assert resolve_output_dir("{outputs}/renders", _NK_DIR, _COMPANION) == "{outputs}/renders"

    def test_dot_relative_dir_resolves_against_nk_script_dir(self) -> None:
        assert resolve_output_dir("./renders", _NK_DIR, _COMPANION) == f"{_NK_DIR}/renders"


class TestBuildMacroMap:
    def test_missing_project_yml_yields_empty_map(self, tmp_path: Path) -> None:
        assert build_macro_map(tmp_path) == {}

    def test_relative_directory_macro_resolves_against_workspace_dir(self, tmp_path: Path) -> None:
        _write_project_yml(tmp_path, "griptape_outputs")
        workspace = tmp_path / "comp"
        macro_map = build_macro_map(tmp_path, workspace_dir=workspace)
        assert macro_map["outputs"] == f"{workspace.as_posix()}/griptape_outputs"

    def test_relative_directory_macro_resolves_against_bundle_when_no_workspace(self, tmp_path: Path) -> None:
        _write_project_yml(tmp_path, "griptape_outputs")
        macro_map = build_macro_map(tmp_path)
        assert macro_map["outputs"] == f"{tmp_path.as_posix()}/griptape_outputs"

    def test_absolute_directory_macro_is_kept(self, tmp_path: Path) -> None:
        _write_project_yml(tmp_path, "/renders/shot_010")
        macro_map = build_macro_map(tmp_path, workspace_dir=tmp_path / "comp")
        assert macro_map["outputs"] == "/renders/shot_010"


class TestResolveMacroPath:
    def test_plain_path_is_unchanged(self) -> None:
        assert resolve_macro_path("/renders/out.png", {"outputs": "/x"}) == "/renders/out.png"

    def test_known_macro_is_substituted(self) -> None:
        assert resolve_macro_path("{outputs}/out.png", {"outputs": "/renders"}) == "/renders/out.png"

    def test_unknown_macro_is_left_in_place(self) -> None:
        assert resolve_macro_path("{nope}/out.png", {"outputs": "/renders"}) == "{nope}/out.png"


class TestSerializeOutput:
    def test_empty_output_yields_empty_dict(self) -> None:
        assert serialize_output(None, {}) == {}
        assert serialize_output({}, {}) == {}

    def test_none_parameter_value_becomes_empty_string(self) -> None:
        assert serialize_output({"Node": {"caption": None}}, {}) == {"caption": ""}

    def test_url_artifact_macro_is_resolved_to_absolute_path(self) -> None:
        output = {"Node": {"image": _FakeUrlArtifact("{outputs}/gen.png")}}
        assert serialize_output(output, {"outputs": "/renders"}) == {"image": "/renders/gen.png"}

    def test_unix_file_uri_keeps_leading_slash(self) -> None:
        output = {"Node": {"image": _FakeUrlArtifact("file:///renders/gen.png")}}
        assert serialize_output(output, {}) == {"image": "/renders/gen.png"}

    def test_windows_file_uri_drops_slash_before_drive_letter(self) -> None:
        output = {"Node": {"image": _FakeUrlArtifact("file:///C:/renders/gen.png")}}
        assert serialize_output(output, {}) == {"image": "C:/renders/gen.png"}

    def test_binary_artifact_value_is_summarized(self) -> None:
        output = {"Node": {"blob": _FakeValueArtifact(b"1234")}}
        assert serialize_output(output, {}) == {"blob": "<binary 4 bytes>"}

    def test_plain_value_is_stringified_and_macro_resolved(self) -> None:
        output = {"Node": {"path": "{outputs}/out.exr", "count": 3}}
        assert serialize_output(output, {"outputs": "/renders"}) == {"path": "/renders/out.exr", "count": "3"}

    def test_non_dict_node_entry_is_skipped(self) -> None:
        assert serialize_output({"Node": "not a dict"}, {}) == {}


def _write_project_yml(bundle_dir: Path, outputs_path_macro: str) -> None:
    template = ProjectTemplate(
        project_template_schema_version=ProjectTemplate.LATEST_SCHEMA_VERSION,
        name="test_project",
        situations={},
        directories={"outputs": DirectoryDefinition(name="outputs", path_macro=outputs_path_macro)},
    )
    (bundle_dir / "project.yml").write_text(template.to_yaml(), encoding="utf-8")
