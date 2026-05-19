from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from execution.installations import (
    LaunchMode,
    NukeInstallation,
    auto_discover_installations,
    build_launch_command,
    find_installation,
    merged_installations,
)


def _inst(**kwargs) -> NukeInstallation:
    defaults = {"display_name": "Nuke16", "executable_path": "/opt/nuke16/nuke"}
    return NukeInstallation(**{**defaults, **kwargs})


def test_launch_mode_values():
    assert LaunchMode.DIRECT.value == "direct"
    assert LaunchMode.REZ.value == "rez"
    assert LaunchMode.SHOTGRID_FLOW.value == "shotgrid_flow"
    assert LaunchMode.CUSTOM.value == "custom"


def test_nuke_installation_roundtrips_to_dict():
    inst = NukeInstallation(
        display_name="Nuke 16.0v3",
        executable_path="/opt/nuke/nuke16",
        launch_mode=LaunchMode.REZ,
        launch_args="nuke-16 ocio-2",
        env_overrides={"OCIO": "/studio/ocio/config.ocio"},
        notes="Studio standard",
    )
    assert NukeInstallation.from_dict(inst.to_dict()) == inst


def test_build_launch_command_direct():
    inst = _inst(launch_mode=LaunchMode.DIRECT)
    cmd = build_launch_command(inst, "runner.py", "in.json", "out.json")
    assert cmd == ["/opt/nuke16/nuke", "-t", "runner.py", "--manifest", "in.json", "--output-manifest", "out.json"]


def test_build_launch_command_rez():
    inst = _inst(launch_mode=LaunchMode.REZ, launch_args="nuke-16 ocio-2.4")
    cmd = build_launch_command(inst, "runner.py", "in.json", "out.json")
    assert cmd == [
        "rez-env",
        "nuke-16",
        "ocio-2.4",
        "--",
        "nuke",
        "-t",
        "runner.py",
        "--manifest",
        "in.json",
        "--output-manifest",
        "out.json",
    ]


def test_build_launch_command_custom_substitutes_tokens():
    inst = _inst(
        display_name="Nuke16",
        launch_mode=LaunchMode.CUSTOM,
        launch_args="/studio/launch.sh --version {display_name} --script {script}",
    )
    cmd = build_launch_command(inst, "runner.py", "in.json", "out.json")
    assert cmd[:5] == ["/studio/launch.sh", "--version", "Nuke16", "--script", "runner.py"]
    assert "--manifest" in cmd
    assert "--output-manifest" in cmd


def test_build_launch_command_shotgrid_raises():
    inst = _inst(launch_mode=LaunchMode.SHOTGRID_FLOW)
    with pytest.raises(NotImplementedError, match="ShotGrid"):
        build_launch_command(inst, "runner.py", "in.json", "out.json")


def test_build_launch_command_unknown_mode_raises():
    inst = _inst()
    inst = dataclasses.replace(inst, launch_mode=object())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError):
        build_launch_command(inst, "runner.py", "in.json", "out.json")


def test_merged_installations_deduplicates_by_path():
    configured = [_inst(display_name="My Nuke 16", executable_path="/opt/nuke16")]
    discovered = [_inst(display_name="nuke16", executable_path="/opt/nuke16")]  # same path

    cfg_mock = MagicMock()
    cfg_mock.get_config_value.return_value = {"My Nuke 16": configured[0].to_dict()}

    with patch("execution.installations.auto_discover_installations", return_value=discovered):
        result = merged_installations(cfg_mock)

    assert len(result) == 1
    assert result[0].display_name == "My Nuke 16"


def test_find_installation_returns_none_on_miss():
    cfg_mock = MagicMock()
    cfg_mock.get_config_value.return_value = {}
    with patch("execution.installations.auto_discover_installations", return_value=[]):
        assert find_installation("does-not-exist", cfg_mock) is None


def test_auto_discover_installations_wraps_discovery():
    with patch(
        "publish_gizmo.nuke_discovery.discover_nuke_executables",
        return_value=["/opt/Nuke16.0v3/nuke16", "/opt/Nuke15.0/nuke15"],
    ):
        result = auto_discover_installations()
    assert len(result) == 2
    assert result[0].display_name == "nuke16"
    assert result[0].executable_path == "/opt/Nuke16.0v3/nuke16"
    assert result[0].launch_mode == LaunchMode.DIRECT


def test_auto_discover_parses_annotator_version_from_path():
    with patch(
        "publish_gizmo.nuke_discovery.discover_nuke_executables",
        return_value=["/opt/Nuke16.0v3/Nuke16.0v3", "/opt/Nuke15.1v2/Nuke15.1v2"],
    ):
        result = auto_discover_installations()
    assert result[0].annotator_nuke_version == 16
    assert result[1].annotator_nuke_version == 15


def test_nuke_installation_roundtrip_includes_annotator_version():
    inst = _inst(annotator_nuke_version=15)
    assert NukeInstallation.from_dict(inst.to_dict()).annotator_nuke_version == 15
