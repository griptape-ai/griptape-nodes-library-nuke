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


def compute_gizmo_install_path_choices() -> list[str]:
    """Return candidate gizmo install directories (excluding 'Custom path…').

    ``~/.nuke`` is always listed first as it is the most common install target.
    """
    candidates: list[str] = []
    seen_keys: set[str] = set()

    def add_path(p: str) -> None:
        if not p or not str(p).strip():
            return
        key = normalize_path_str(p)
        if key not in seen_keys:
            seen_keys.add(key)
            candidates.append(key)

    # ~/.nuke is the standard user plugin directory — list it first.
    add_path(str(Path.home() / ".nuke"))

    for seg in nuke_path_env_segments():
        add_path(seg)

    return candidates


def default_gizmo_path(candidates: list[str]) -> str:
    """Pick the best default gizmo path from a list of candidates (excluding 'Custom path…').

    ``~/.nuke`` is always preferred as the default regardless of what other paths exist.
    """
    clean = [c for c in candidates if c != GIZMO_INSTALL_CUSTOM]
    dot_nuke = normalize_path_str(str(Path.home() / ".nuke"))
    for c in clean:
        if normalize_path_str(c) == dot_nuke:
            return c
    if clean:
        return clean[0]
    return dot_nuke
