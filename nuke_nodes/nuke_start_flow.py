import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from griptape_nodes.exe_types.core_types import NodeMessageResult, Parameter
from griptape_nodes.exe_types.node_types import StartNode
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString
from griptape_nodes.traits.button import Button, ButtonDetailsMessagePayload
from griptape_nodes.traits.file_system_picker import FileSystemPicker
from griptape_nodes.traits.options import Options

logger = logging.getLogger(__name__)

NUKE_REFRESH_PLACEHOLDER = "Click Refresh to scan for Nuke installations"
NO_NUKE_INSTALLATIONS_MSG = "No Nuke installations found"
GIZMO_INSTALL_CUSTOM = "Custom path…"


def _normalize_path_str(path_str: str) -> str:
    p = Path(path_str).expanduser()
    try:
        return str(p.resolve())
    except OSError:
        return str(p)


def _install_root_for_nuke_executable(exe: Path) -> Path:
    """Folder to show in the UI (e.g. /Applications/Nuke16.0v7), not the deep .app/Contents/MacOS path."""
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


class NukeStartFlow(StartNode):
    def __init__(
        self,
        name: str,
        metadata: dict[Any, Any] | None = None,
    ) -> None:
        if metadata is None:
            metadata = {}
        metadata["showaddparameter"] = True
        super().__init__(name, metadata)
        self._nuke_install_root_to_executable: dict[str, str] = {}

        self.add_parameter(
            ParameterString(
                name="nuke",
                tooltip=(
                    "Nuke install location (version folder under /Applications, Program Files, etc.). "
                    "The main Nuke binary for that install is used automatically. Refresh rescans."
                ),
                default_value=NUKE_REFRESH_PLACEHOLDER,
                traits={
                    Options(choices=[NUKE_REFRESH_PLACEHOLDER]),
                    Button(
                        icon="list-restart",
                        on_click=self._refresh_nuke_installations,
                    ),
                },
            )
        )
        home_dot_nuke = str(Path.home() / ".nuke")
        self.add_parameter(
            ParameterString(
                name="gizmo_install_path",
                tooltip=(
                    "Directory where the gizmo should be installed (plugins / nukescripts; see Foundry loading "
                    "gizmos docs). If NUKE_PATH is set and that path exists on disk, it is selected first; otherwise "
                    "the first path for your OS based on the selected Nuke install. Choose “Custom path…” to set a "
                    "directory via the custom path field below. Matches .env.example conventions."
                ),
                default_value=home_dot_nuke,
                traits={
                    Options(choices=[home_dot_nuke]),
                },
            )
        )
        self.add_parameter(
            ParameterString(
                name="custom_gizmo_path",
                tooltip="Shown when you pick “Custom path…” above. Directory where the gizmo should be installed.",
                default_value=str(Path.home() / ".nuke"),
                traits={
                    FileSystemPicker(allow_directories=True, allow_create=True),
                },
                hide=True,
            )
        )
        self._sync_nuke_installation_choices()
        self._sync_gizmo_install_path_choices()

    def after_value_set(self, parameter: Parameter, value: Any) -> None:
        if parameter.name == "nuke":
            self._sync_gizmo_install_path_choices()
        elif parameter.name == "gizmo_install_path":
            self._update_custom_gizmo_visibility()
        return super().after_value_set(parameter, value)

    def _nuke_path_env_segments(self) -> list[str]:
        raw = os.environ.get("NUKE_PATH", "").strip()
        if not raw:
            return []
        seen: set[str] = set()
        out: list[str] = []
        for part in raw.split(os.pathsep):
            part = part.strip()
            if not part:
                continue
            norm = _normalize_path_str(part)
            if norm not in seen:
                seen.add(norm)
                out.append(norm)
        return out

    def _nuke_exe_value_is_usable(self, nuke: str | None) -> bool:
        if not nuke:
            return False
        if nuke in (NUKE_REFRESH_PLACEHOLDER, NO_NUKE_INSTALLATIONS_MSG):
            return False
        if nuke.startswith("Error scanning"):
            return False
        exe = self._nuke_install_root_to_executable.get(_normalize_path_str(nuke))
        return bool(exe and Path(exe).is_file())

    def _pick_preferred_executable_for_root(self, root: Path, candidates: list[Path]) -> Path:
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

    def _discover_nuke_install_roots_and_map(self) -> tuple[list[str], dict[str, str]]:
        """Return sorted install root paths for the dropdown and a map root -> executable path."""
        exes = self._discover_nuke_executables()
        root_to_candidates: dict[str, list[Path]] = {}
        for exe_str in exes:
            exe = Path(exe_str)
            root = _install_root_for_nuke_executable(exe)
            rk = _normalize_path_str(str(root))
            root_to_candidates.setdefault(rk, []).append(exe)

        root_to_exe: dict[str, str] = {}
        for rk, cands in root_to_candidates.items():
            picked = self._pick_preferred_executable_for_root(Path(rk), cands)
            try:
                root_to_exe[rk] = str(picked.resolve())
            except OSError:
                root_to_exe[rk] = str(picked)

        return sorted(root_to_exe.keys()), root_to_exe

    def _versioned_gizmo_paths_for_exe(self, nuke_exe: str) -> list[str]:
        """Paths relative to the selected Nuke install per OS (see .env.example)."""
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

    def _default_gizmo_path(self, candidates: list[str]) -> str:
        for seg in self._nuke_path_env_segments():
            if Path(seg).is_dir():
                return seg
        for c in candidates:
            if c == GIZMO_INSTALL_CUSTOM:
                continue
            if Path(c).is_dir():
                return c
        for c in candidates:
            if c != GIZMO_INSTALL_CUSTOM:
                return c
        return candidates[0]

    def _update_custom_gizmo_visibility(self) -> None:
        param = self.get_parameter_by_name("custom_gizmo_path")
        if param is None:
            return
        choice = self.get_parameter_value("gizmo_install_path")
        param.hide = choice != GIZMO_INSTALL_CUSTOM

    def _sync_gizmo_install_path_choices(self) -> None:
        try:
            nuke = self.get_parameter_value("nuke")
            current_raw = self.get_parameter_value("gizmo_install_path")

            candidates: list[str] = []
            seen_keys: set[str] = set()

            def add_path(p: str) -> None:
                if not p or not str(p).strip():
                    return
                key = _normalize_path_str(p)
                if key not in seen_keys:
                    seen_keys.add(key)
                    candidates.append(key)

            for seg in self._nuke_path_env_segments():
                add_path(seg)

            if self._nuke_exe_value_is_usable(nuke):
                exe = self._nuke_install_root_to_executable.get(_normalize_path_str(nuke))
                if exe:
                    for p in self._versioned_gizmo_paths_for_exe(exe):
                        add_path(p)

            add_path(str(Path.home() / ".nuke"))

            if not candidates:
                add_path(str(Path.home() / ".nuke"))

            if GIZMO_INSTALL_CUSTOM not in candidates:
                candidates.append(GIZMO_INSTALL_CUSTOM)

            selected = self._default_gizmo_path(candidates)

            if current_raw == GIZMO_INSTALL_CUSTOM:
                selected = GIZMO_INSTALL_CUSTOM
            elif current_raw:
                current_norm = _normalize_path_str(str(current_raw))
                for c in candidates:
                    if c != GIZMO_INSTALL_CUSTOM and _normalize_path_str(c) == current_norm:
                        selected = c
                        break

            self._update_option_choices("gizmo_install_path", candidates, selected)
            self._update_custom_gizmo_visibility()
        except Exception:
            logger.exception("%s: Failed to sync gizmo install path choices", self.name)
            fallback = str(Path.home() / ".nuke")
            choices = [fallback, GIZMO_INSTALL_CUSTOM]
            self._update_option_choices("gizmo_install_path", choices, fallback)
            self._update_custom_gizmo_visibility()

    def _discover_nuke_executables(self) -> list[str]:
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
                root = os.environ.get(env_key)
                if root:
                    roots.append(Path(root))
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

    def _sync_nuke_installation_choices(self) -> None:
        try:
            current = self.get_parameter_value("nuke")
            found, root_map = self._discover_nuke_install_roots_and_map()
            self._nuke_install_root_to_executable = root_map

            if not found:
                self._nuke_install_root_to_executable = {}
                self._update_option_choices("nuke", [NO_NUKE_INSTALLATIONS_MSG], NO_NUKE_INSTALLATIONS_MSG)
                return

            placeholder_values = {NUKE_REFRESH_PLACEHOLDER, NO_NUKE_INSTALLATIONS_MSG}
            selected = found[0]
            if current and current not in placeholder_values:
                cur_norm = _normalize_path_str(str(current))
                if cur_norm in found:
                    selected = cur_norm
                elif Path(current).is_file():
                    migrated = _normalize_path_str(str(_install_root_for_nuke_executable(Path(current))))
                    if migrated in found:
                        selected = migrated

            self._update_option_choices("nuke", found, selected)
        except Exception as e:
            logger.exception("%s: Failed to refresh Nuke installations", self.name)
            self._nuke_install_root_to_executable = {}
            err = f"Error scanning for Nuke: {e}"
            self._update_option_choices("nuke", [err], err)

    def _refresh_nuke_installations(
        self,
        _button: Button,
        _button_details: ButtonDetailsMessagePayload,
    ) -> NodeMessageResult | None:
        self._sync_nuke_installation_choices()
        self._sync_gizmo_install_path_choices()
        return None

    def process(self) -> None:
        pass
