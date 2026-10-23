from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from griptape_nodes.common.project_templates import (
    DEFAULT_PROJECT_TEMPLATE,
    DirectoryDefinition,
    PerPlatformPathMacro,
    PerPlatformProjectPath,
)
from griptape_nodes.retained_mode.events.project_events import (
    GetCurrentProjectRequest,
    GetCurrentProjectResultFailure,
    GetCurrentProjectResultSuccess,
    GetPathForMacroRequest,
    GetPathForMacroResultSuccess,
)

from nuke_host_api import host_paths
from tests.unit.host_api_fakes import FakeEngine, use_engine


@pytest.fixture(autouse=True)
def _engine_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_paths, "active_platform_key", lambda: "linux")


def _project(
    monkeypatch: pytest.MonkeyPatch,
    *,
    workspace_dir: str | PerPlatformProjectPath | None = None,
    directories: dict[str, DirectoryDefinition] | None = None,
    resolved: dict[str, str] | None = None,
) -> FakeEngine:
    template = DEFAULT_PROJECT_TEMPLATE.model_copy(
        update={"workspace_dir": workspace_dir, "directories": directories or {}}
    )
    folders = {"workspace_dir": "/mnt/share", **(resolved or {})}

    def resolve(request: GetPathForMacroRequest) -> Any:
        folder = Path(folders[next(iter(request.parsed_macro.get_variables())).name])
        return GetPathForMacroResultSuccess(resolved_path=folder, absolute_path=folder, result_details="resolved")

    return use_engine(
        monkeypatch,
        {
            GetCurrentProjectRequest: GetCurrentProjectResultSuccess(
                project_info=MagicMock(template=template), result_details="current"
            ),
            GetPathForMacroRequest: resolve,
        },
    )


class TestEnginePath:
    async def test_a_macos_path_under_the_workspace_opens_the_engines_mount(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _project(monkeypatch, workspace_dir=PerPlatformProjectPath(darwin="/Volumes/share", linux="/mnt/share"))

        assert await host_paths.engine_path("/Volumes/share/u/blur.py") == str(Path("/mnt/share/u/blur.py"))

    async def test_a_windows_path_matches_case_insensitively_and_the_most_specific_folder_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _project(
            monkeypatch,
            workspace_dir=PerPlatformProjectPath(windows=r"\\host\share", linux="/mnt/share"),
            directories={
                "renders": DirectoryDefinition(
                    name="renders",
                    path_macro=PerPlatformPathMacro(windows=r"\\host\share\renders", linux="/srv/renders"),
                )
            },
            resolved={"renders": "/srv/renders"},
        )

        assert await host_paths.engine_path(r"\\HOST\Share\renders\a.exr") == str(Path("/srv/renders/a.exr"))

    async def test_the_workspace_is_not_matched_when_an_override_moves_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """{workspace_dir} would resolve to the override, not the folder the project names."""
        _project(
            monkeypatch,
            workspace_dir=PerPlatformProjectPath(darwin="/Volumes/share", linux="/mnt/share"),
            resolved={"workspace_dir": "/srv/override"},
        )

        assert await host_paths.engine_path("/Volumes/share/u/blur.py") == "/Volumes/share/u/blur.py"

    async def test_values_that_need_expansion_are_not_matched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _project(
            monkeypatch,
            workspace_dir=PerPlatformProjectPath(windows=r"%SHARE%\ws", linux="/mnt/share"),
            directories={
                "renders": DirectoryDefinition(
                    name="renders", path_macro=PerPlatformPathMacro(windows=r"{workspace_dir}\renders", linux="/srv")
                )
            },
        )

        assert await host_paths.engine_path(r"C:\ws\u\blur.py") == r"C:\ws\u\blur.py"

    async def test_a_path_no_project_folder_covers_is_sent_as_written(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _project(monkeypatch, workspace_dir=PerPlatformProjectPath(darwin="/Volumes/share", linux="/mnt/share"))

        assert await host_paths.engine_path("/Volumes/other/blur.py") == "/Volumes/other/blur.py"

    async def test_without_a_current_project_the_path_is_sent_as_written(self, monkeypatch: pytest.MonkeyPatch) -> None:
        use_engine(monkeypatch, {GetCurrentProjectRequest: GetCurrentProjectResultFailure(result_details="none")})

        assert await host_paths.engine_path("/Volumes/share/u/blur.py") == "/Volumes/share/u/blur.py"

    async def test_an_existing_local_file_never_reaches_the_engine(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        local_file = tmp_path / "blur.py"
        local_file.write_text("")
        engine = use_engine(monkeypatch, {})

        assert await host_paths.engine_path(str(local_file)) == str(local_file)
        assert engine.requests == []

    async def test_a_relative_path_never_reaches_the_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = use_engine(monkeypatch, {})

        assert await host_paths.engine_path("shots/blur.py") == "shots/blur.py"
        assert engine.requests == []
