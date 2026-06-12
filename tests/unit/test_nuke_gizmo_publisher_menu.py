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
    """Must guard pluginRemovePath (undocumented) then re-add before nuke.plugins().

    pluginAddPath is idempotent on an already-registered path — without the remove,
    Nuke skips the directory walk and nuke.plugins() misses newly written gizmos.
    pluginRemovePath must be guarded with hasattr to avoid crashing on Nuke versions
    that don't expose it.
    """
    code = _extract_menu_code()
    assert "hasattr(nuke, 'pluginRemovePath')" in code
    assert "nuke.pluginRemovePath(" in code
    assert "nuke.pluginAddPath(" in code
    assert "nuke.plugins(" in code
    assert code.index("hasattr(nuke, 'pluginRemovePath')") < code.index("nuke.pluginRemovePath(")


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


def test_menu_code_never_removes_entire_griptape_menu() -> None:
    """Wiping Nodes > Griptape deletes third-party items (e.g. Nuke's built-in
    Griptape workflow node) — refresh must only touch entries it added (issue #69)."""
    code = _extract_menu_code()
    assert "nodes_toolbar.removeItem('Griptape')" not in code
    assert 'nodes_toolbar.removeItem("Griptape")' not in code


def test_menu_code_tracks_and_removes_only_own_menu_items() -> None:
    """Refresh must record added labels and remove only tracked items before re-populating."""
    code = _extract_menu_code()
    assert "_GRIPTAPE_MENU_ITEMS = []" in code
    assert "griptape_nodes.removeItem(" in code
    assert "_GRIPTAPE_MENU_ITEMS.append(" in code
    # Tracked-item removal must precede re-population.
    assert code.index("griptape_nodes.removeItem(") < code.index("griptape_nodes.addCommand(")


def test_menu_code_reuses_existing_griptape_menu() -> None:
    """addMenu returns the existing menu when present — get-or-create, never recreate."""
    code = _extract_menu_code()
    assert "nodes_toolbar.addMenu('Griptape')" in code
    # addMenu (get-or-create) must come before any removeItem on the submenu.
    assert code.index("nodes_toolbar.addMenu('Griptape')") < code.index("griptape_nodes.removeItem(")


def test_menu_code_warns_on_remote_mount() -> None:
    """Must include remote-mount heuristic and print warning inside the Qt guard block.

    QFileSystemWatcher silently fails on NFS/SMB mounts (kernel limitation), so
    we warn at startup when the install dir looks like a network path.
    """
    code = _extract_menu_code()
    assert "_griptape_is_remote_mount" in code
    assert "Refresh Griptape Gizmos" in code
    assert "network mount" in code
    # Helper and warning must be inside the if _QT_AVAILABLE block (headless safe).
    qt_guard_idx = code.rindex("if _QT_AVAILABLE")
    assert code.index("_griptape_is_remote_mount") > qt_guard_idx
