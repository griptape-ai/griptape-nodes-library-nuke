from __future__ import annotations

import ast
from pathlib import Path


def _extract_menu_code() -> str:
    """Parse nuke_gizmo_publisher.py and extract the menu_code string literal
    from _regenerate_menu_py without importing the module (avoids griptape_nodes dependency)."""
    src = (Path(__file__).parent.parent.parent / "publish_gizmo" / "nuke_gizmo_publisher.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_regenerate_menu_py":
            for stmt in ast.walk(node):
                if (
                    isinstance(stmt, ast.Assign)
                    and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id == "menu_code"
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    return stmt.value.value
    msg = "menu_code string not found in _regenerate_menu_py"
    raise AssertionError(msg)


def test_menu_code_forces_plugin_path_rescan() -> None:
    """Must remove then re-add the plugin path before calling nuke.plugins().

    pluginAddPath is idempotent on an already-registered path — without the remove,
    Nuke skips the directory walk and nuke.plugins() misses newly written gizmos.
    """
    code = _extract_menu_code()
    assert "nuke.pluginRemovePath(" in code
    assert "nuke.pluginAddPath(" in code
    assert "nuke.plugins(" in code
    assert code.index("nuke.pluginRemovePath(") < code.index("nuke.pluginAddPath(")


def test_menu_code_contains_file_system_watcher() -> None:
    """Must wire a QFileSystemWatcher for zero-click auto-refresh."""
    code = _extract_menu_code()
    assert "QFileSystemWatcher" in code
    assert "_GRIPTAPE_WATCHER" in code
    assert "directoryChanged" in code


def test_menu_code_has_pyside6_pyside2_fallback() -> None:
    """Must attempt PySide6 import first, fall back to PySide2."""
    code = _extract_menu_code()
    assert "PySide6" in code
    assert "PySide2" in code
    assert code.index("PySide6") < code.index("PySide2")


def test_menu_code_skips_watcher_when_qt_unavailable() -> None:
    """Watcher block must be guarded by _QT_AVAILABLE so nuke -t headless doesn't error."""
    code = _extract_menu_code()
    assert "_QT_AVAILABLE" in code
    watcher_idx = code.index("_GRIPTAPE_WATCHER = QFileSystemWatcher")
    guard_idx = code.rindex("if _QT_AVAILABLE", 0, watcher_idx)
    assert guard_idx < watcher_idx
