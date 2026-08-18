"""Tests for _customize_project_yml output filename macro and collision policy."""

from __future__ import annotations

import ast
from pathlib import Path

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


def _find_directory_definition_call(func: ast.FunctionDef) -> ast.Call:
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            func_node = node.func
            if isinstance(func_node, ast.Name) and func_node.id == "DirectoryDefinition":
                return node
            if isinstance(func_node, ast.Attribute) and func_node.attr == "DirectoryDefinition":
                return node
    msg = "DirectoryDefinition() call not found in _customize_project_yml"
    raise AssertionError(msg)


def _get_keyword_value(call: ast.Call, name: str) -> ast.expr:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    msg = f"keyword '{name}' not found in SituationTemplate call"
    raise AssertionError(msg)


class TestCustomizeProjectYmlOutput:
    def test_save_node_output_macro_is_versioned(self) -> None:
        func = _get_customize_project_yml_source()
        call = _find_situation_template_call(func)
        macro_node = _get_keyword_value(call, "macro")
        assert isinstance(macro_node, ast.Constant)
        assert isinstance(macro_node.value, str)
        assert "_v{_index?:04}" in macro_node.value, (
            f"Expected versioned macro containing '_v{{_index?:04}}', got: {macro_node.value!r}"
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

    def test_outputs_path_macro_uses_shared_constant(self) -> None:
        """The gizmo's Run tab help text quotes OUTPUTS_DIR_NAME; the project.yml
        must be stamped from the same constant or the two silently drift."""
        func = _get_customize_project_yml_source()
        call = _find_directory_definition_call(func)
        path_macro_node = _get_keyword_value(call, "path_macro")
        assert isinstance(path_macro_node, ast.Name), (
            f"Expected path_macro to reference OUTPUTS_DIR_NAME, got: {ast.dump(path_macro_node)}"
        )
        assert path_macro_node.id == "OUTPUTS_DIR_NAME"
