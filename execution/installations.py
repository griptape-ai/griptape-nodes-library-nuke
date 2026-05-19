from __future__ import annotations

import dataclasses
import enum
import os
import re
import shlex
from pathlib import Path
from typing import Any


def _parse_nuke_major(name: str) -> int:
    """Extract the major version integer from a Nuke executable name or path stem."""
    m = re.search(r"[Nn]uke(\d+)", name)
    return int(m.group(1)) if m else 0


class LaunchMode(enum.Enum):
    DIRECT = "direct"
    REZ = "rez"
    SHOTGRID_FLOW = "shotgrid_flow"
    CUSTOM = "custom"


@dataclasses.dataclass
class NukeInstallation:
    """A named Nuke installation entry from Engine Settings."""

    display_name: str
    executable_path: str
    launch_mode: LaunchMode = LaunchMode.DIRECT
    launch_args: str = ""
    env_overrides: dict[str, str] = dataclasses.field(default_factory=dict)
    notes: str = ""
    annotator_nuke_version: int = 16

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NukeInstallation:
        return cls(
            display_name=d["display_name"],
            executable_path=d["executable_path"],
            launch_mode=LaunchMode(d.get("launch_mode", "direct")),
            launch_args=d.get("launch_args", ""),
            env_overrides=dict(d.get("env_overrides", {})),
            notes=d.get("notes", ""),
            annotator_nuke_version=int(d.get("annotator_nuke_version", 16)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "executable_path": self.executable_path,
            "launch_mode": self.launch_mode.value,
            "launch_args": self.launch_args,
            "env_overrides": self.env_overrides,
            "notes": self.notes,
            "annotator_nuke_version": self.annotator_nuke_version,
        }


def build_launch_command(
    installation: NukeInstallation,
    runner_script: str,
    manifest_path: str,
    output_manifest_path: str,
) -> list[str]:
    """Return the full argv for launching nuke -t <runner> via this installation."""
    nuke_tail = ["-t", runner_script, "--manifest", manifest_path, "--output-manifest", output_manifest_path]

    if installation.launch_mode == LaunchMode.DIRECT:
        return [installation.executable_path, *nuke_tail]

    if installation.launch_mode == LaunchMode.REZ:
        packages = installation.launch_args.strip() or "nuke"
        return ["rez-env", *shlex.split(packages), "--", "nuke", *nuke_tail]

    if installation.launch_mode == LaunchMode.CUSTOM:
        template = installation.launch_args or installation.executable_path
        expanded = template.replace("{display_name}", installation.display_name).replace("{script}", runner_script)
        return [*shlex.split(expanded), *nuke_tail]

    if installation.launch_mode == LaunchMode.SHOTGRID_FLOW:
        raise NotImplementedError("ShotGrid/Flow launcher not yet implemented")

    raise NotImplementedError(f"Unknown launch mode: {installation.launch_mode}")


def list_configured_installations(config_manager: Any) -> list[NukeInstallation]:
    """Read nuke.installations from engine settings.

    Accepts either a list of dicts (each with a display_name key) or a dict keyed
    by display name. The list form is what the engine persists in the user config;
    the dict form is the library default that avoids the engine's set()-based list merge.
    """
    raw = config_manager.get_config_value("nuke.installations") or {}
    if isinstance(raw, list):
        return [NukeInstallation.from_dict(d) for d in raw]
    return [NukeInstallation.from_dict({"display_name": name, **data}) for name, data in raw.items()]


def auto_discover_installations() -> list[NukeInstallation]:
    """Return NukeInstallation entries from filesystem discovery."""
    from publish_gizmo.nuke_discovery import discover_nuke_executables

    installations: list[NukeInstallation] = []
    for exe_path in discover_nuke_executables():
        stem = Path(exe_path).stem or exe_path
        major = _parse_nuke_major(exe_path)
        installations.append(
            NukeInstallation(display_name=stem, executable_path=exe_path, annotator_nuke_version=major)
        )
    return installations


def merged_installations(config_manager: Any) -> list[NukeInstallation]:
    """Return configured installations first, then auto-discovered ones not already listed."""
    configured = list_configured_installations(config_manager)
    configured_paths = {os.path.realpath(inst.executable_path) for inst in configured}
    discovered = [
        d for d in auto_discover_installations() if os.path.realpath(d.executable_path) not in configured_paths
    ]
    return [*configured, *discovered]


def find_installation(display_name: str, config_manager: Any) -> NukeInstallation | None:
    """Find an installation by display name from the merged list."""
    for inst in merged_installations(config_manager):
        if inst.display_name == display_name:
            return inst
    return None
