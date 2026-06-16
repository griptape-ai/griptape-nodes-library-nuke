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


def test_menu_code_discovers_via_glob_and_loads_gizmos() -> None:
    """Refresh must discover gizmos from the filesystem and register them.

    nuke.plugins() returns a list Nuke caches at startup, so it misses gizmos
    published during the session ("nothing happens" on refresh). The refresh must
    glob the directory for the current files and nuke.load() each one by full
    path so nuke.createNode() can instantiate a gizmo added after launch.
    """
    code = _extract_menu_code()
    assert "import glob" in code
    assert "glob.glob(" in code
    assert "nuke.load(" in code
    assert "nuke.pluginAddPath(" in code
    # The stale cached-discovery call must be gone.
    assert "nuke.plugins(nuke.ALL" not in code
    assert "pluginRemovePath" not in code


def test_menu_code_contains_file_system_watcher() -> None:
    """Must wire a QFileSystemWatcher for zero-click auto-refresh."""
    code = _extract_menu_code()
    assert "QFileSystemWatcher" in code
    assert "_GRIPTAPE_WATCHER" in code
    assert "directoryChanged" in code


def test_menu_code_watcher_never_calls_nuke_automatically() -> None:
    """The watcher must not auto-invoke the refresh (issue #78).

    directoryChanged is delivered from QFileSystemWatcher's engine thread and
    fires repeatedly while a publish writes several files into the watched dir.
    Driving Nuke's plugin/menu C++ APIs from that asynchronous callback corrupts
    Nuke's internal state and crashes the host. The watcher must only notify; the
    rescan happens on the user-initiated command, when Nuke is idle.
    """
    code = _extract_menu_code()
    # The watcher hands off to a debounce timer, never to the refresh.
    assert "directoryChanged.connect(lambda _path: _GRIPTAPE_NOTIFY_TIMER.start())" in code
    assert "directoryChanged.connect(lambda _path: _refresh_griptape_menu())" not in code
    assert "directoryChanged.connect(lambda _path: _GRIPTAPE_REFRESH_TIMER.start())" not in code
    # _refresh_griptape_menu is only called at startup and from the manual command.
    assert "addCommand('Refresh Griptape Gizmos', _refresh_griptape_menu)" in code


def test_menu_code_debounces_watcher_notification() -> None:
    """directoryChanged must coalesce through a single-shot QTimer so the hint
    prints once per publish, after the writes settle, not once per file."""
    code = _extract_menu_code()
    assert "QTimer" in code
    assert "setSingleShot(True)" in code
    assert "_GRIPTAPE_NOTIFY_TIMER" in code


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


def test_menu_code_is_add_only_never_calls_remove_item() -> None:
    """Refresh must never call removeItem on the shared Griptape menu (issue #78).

    removeItem on the shared Nodes > Griptape menu crashes the host. The refresh
    is add-only: it tracks node names it has added in _GRIPTAPE_ADDED and skips
    them on later refreshes instead of removing and re-adding.
    """
    code = _extract_menu_code()
    assert "removeItem(" not in code
    assert "_GRIPTAPE_ADDED = set()" in code
    assert "nn not in _GRIPTAPE_ADDED" in code
    assert "_GRIPTAPE_ADDED.add(" in code


def test_menu_code_reuses_existing_griptape_menu() -> None:
    """addMenu returns the existing menu when present — get-or-create, never recreate."""
    code = _extract_menu_code()
    assert "nodes_toolbar.addMenu('Griptape')" in code
    # Per-workflow submenus are also get-or-create (addMenu), never recreated.
    assert "griptape_nodes.addMenu(label)" in code


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
