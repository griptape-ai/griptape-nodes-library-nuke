"""Nuke installation and gizmo path discovery utilities.

These functions are used both by the publish options provider (at publish time)
and by NukeStartFlow (for interactive node parameters).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


GIZMO_INSTALL_CUSTOM = "Custom path\u2026"


def normalize_path_str(path_str: str) -> str:
    p = Path(path_str).expanduser()
    try:
        return str(p.resolve())
    except OSError:
        return str(p)


def install_root_for_nuke_executable(exe: Path) -> Path:
    """Return the version folder to show in the UI (e.g. /Applications/Nuke16.0v7)."""
    try:
        exe_r = exe.resolve()
    except OSError:
        exe_r = exe
    if sys.platform == "darwin":
        macos = exe_r.parent
        if macos.name == "MacOS":
            contents = macos.parent
            inner = contents.parent
            if inner.suffix == ".app":
                outer = inner.parent
                if outer == Path("/Applications"):
                    return inner
                return outer
            return inner
        return exe_r.parent
    return exe_r.parent


def pick_preferred_executable_for_root(root: Path, candidates: list[Path]) -> Path:
    """Prefer e.g. Nuke16.0v7.app when root is folder Nuke16.0v7."""
    root_name = root.name
    sorted_cands = sorted(candidates, key=lambda p: str(p))
    for c in sorted_cands:
        try:
            if c.parent.name == "MacOS":
                bundle = c.parent.parent.parent
                if bundle.suffix == ".app" and bundle.stem == root_name:
                    return c
        except (IndexError, OSError):
            continue
    return sorted_cands[0]


def discover_nuke_executables() -> list[str]:
    """Return sorted unique paths to Nuke executables found on this machine."""
    paths: list[str] = []
    seen: set[str] = set()

    def add(candidate: Path) -> None:
        if not candidate.is_file():
            return
        # macOS app binaries may not report X_OK reliably; Windows uses .exe only.
        if sys.platform not in ("win32", "darwin") and not os.access(candidate, os.X_OK):
            return
        try:
            key = str(candidate.resolve())
        except OSError:
            key = str(candidate)
        if key not in seen:
            seen.add(key)
            paths.append(key)

    if sys.platform == "darwin":
        applications = Path("/Applications")

        def add_executables_in_macos(macos_dir: Path) -> None:
            if not macos_dir.is_dir():
                return
            for pattern in ("Nuke*", "nuke*"):
                for exe in macos_dir.glob(pattern):
                    if "crash" in exe.name.lower():
                        continue
                    add(exe)

        if applications.is_dir():
            for install in sorted(applications.glob("Nuke*")):
                if not install.is_dir():
                    continue
                macos_dir = install / "Contents" / "MacOS"
                if macos_dir.is_dir():
                    add_executables_in_macos(macos_dir)
                else:
                    # e.g. /Applications/Nuke16.0v7 with inner Nuke16.0v7.app (no top-level Contents)
                    for app_bundle in sorted(install.glob("*.app")):
                        add_executables_in_macos(app_bundle / "Contents" / "MacOS")
                    for pattern in ("Nuke*", "nuke*"):
                        for exe in install.glob(pattern):
                            add(exe)
    elif sys.platform == "win32":
        roots = []
        for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
            root_str = os.environ.get(env_key)
            if root_str:
                roots.append(Path(root_str))
        for root in roots:
            if not root.is_dir():
                continue
            for nuke_dir in sorted(root.glob("Nuke*")):
                if nuke_dir.is_dir():
                    for exe in nuke_dir.glob("Nuke*.exe"):
                        add(exe)
    else:
        search_roots = [Path("/usr/local"), Path("/opt"), Path.home()]
        for base in search_roots:
            if not base.is_dir():
                continue
            for nuke_dir in base.glob("Nuke*"):
                if nuke_dir.is_dir():
                    for exe in nuke_dir.glob("Nuke*"):
                        if exe.is_file():
                            add(exe)

    for name in ("Nuke", "nuke"):
        found = shutil.which(name)
        if found:
            add(Path(found))

    paths.sort()
    return paths


def discover_nuke_install_roots_and_map() -> tuple[list[str], dict[str, str]]:
    """Return (sorted install root paths, root -> executable path map)."""
    exes = discover_nuke_executables()
    root_to_candidates: dict[str, list[Path]] = {}
    for exe_str in exes:
        exe = Path(exe_str)
        root = install_root_for_nuke_executable(exe)
        rk = normalize_path_str(str(root))
        root_to_candidates.setdefault(rk, []).append(exe)

    root_to_exe: dict[str, str] = {}
    for rk, cands in root_to_candidates.items():
        picked = pick_preferred_executable_for_root(Path(rk), cands)
        try:
            root_to_exe[rk] = str(picked.resolve())
        except OSError:
            root_to_exe[rk] = str(picked)

    return sorted(root_to_exe.keys()), root_to_exe


def nuke_path_env_segments() -> list[str]:
    """Return normalized paths from the NUKE_PATH environment variable."""
    raw = os.environ.get("NUKE_PATH", "").strip()
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        norm = normalize_path_str(part)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def versioned_gizmo_paths_for_exe(nuke_exe: str) -> list[str]:
    """Return OS-specific plugin paths relative to the selected Nuke install."""
    exe_path = Path(nuke_exe)
    try:
        exe = exe_path.resolve()
    except OSError:
        exe = exe_path

    paths: list[str] = []
    if sys.platform == "darwin":
        macos = exe.parent
        if macos.name == "MacOS":
            paths.append(str(macos / "plugins"))
            contents = macos.parent
            bundle_or_install = contents.parent
            if bundle_or_install.suffix == ".app":
                outer = bundle_or_install.parent
                paths.append(str(outer / "plugins" / "nukescripts"))
            else:
                paths.append(str(bundle_or_install / "plugins" / "nukescripts"))
        else:
            root = exe.parent
            paths.extend([str(root / "plugins" / "nukescripts"), str(root / "plugins")])
    elif sys.platform == "win32":
        root = exe.parent
        paths.extend([str(root / "plugins" / "nukescripts"), str(root / "plugins")])
    else:
        root = exe.parent
        paths.extend([str(root / "plugins" / "nukescripts"), str(root / "plugins")])
    return paths


def compute_gizmo_install_path_choices(selected_nuke: str | None, root_to_exe: dict[str, str]) -> list[str]:
    """Return candidate gizmo install directories (excluding 'Custom path…')."""
    candidates: list[str] = []
    seen_keys: set[str] = set()

    def add_path(p: str) -> None:
        if not p or not str(p).strip():
            return
        key = normalize_path_str(p)
        if key not in seen_keys:
            seen_keys.add(key)
            candidates.append(key)

    for seg in nuke_path_env_segments():
        add_path(seg)

    if selected_nuke:
        norm = normalize_path_str(selected_nuke)
        exe = root_to_exe.get(norm)
        if exe and Path(exe).is_file():
            for p in versioned_gizmo_paths_for_exe(exe):
                add_path(p)

    add_path(str(Path.home() / ".nuke"))

    if not candidates:
        add_path(str(Path.home() / ".nuke"))

    return candidates


def default_gizmo_path(candidates: list[str]) -> str:
    """Pick the best default gizmo path from a list of candidates (excluding 'Custom path…')."""
    clean = [c for c in candidates if c != GIZMO_INSTALL_CUSTOM]
    for seg in nuke_path_env_segments():
        if Path(seg).is_dir():
            return seg
    for c in clean:
        if Path(c).is_dir():
            return c
    if clean:
        return clean[0]
    return str(Path.home() / ".nuke")
