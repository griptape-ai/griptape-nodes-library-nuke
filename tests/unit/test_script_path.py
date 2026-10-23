"""Tests that Script Path text becomes a machine-independent absolute path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from griptape_nodes.retained_mode.events.library_events import (
    GetLibrarySourceInfoRequest,
    GetLibrarySourceInfoResultSuccess,
)
from griptape_nodes.retained_mode.events.project_events import (
    GetPathForMacroRequest,
    GetPathForMacroResultFailure,
    GetPathForMacroResultSuccess,
    PathResolutionFailureReason,
)

from nuke_nodes import script_path as script_path_module
from nuke_nodes.script_path import (
    ScriptPathResolution,
    describe_failure,
    library_dir,
    resolve_script_path,
    workflow_anchor_dir,
)


class FakeLibraryManager:
    """Stands in for GriptapeNodes.LibraryManager(), mapping a node type to a library name."""

    def __init__(self, library_name: str | None) -> None:
        self._library_name = library_name

    def get_library_name_for_node_type(self, node_type: str) -> str | None:  # noqa: ARG002
        return self._library_name

    @property
    def catalog(self) -> FakeLibraryManager:
        return self


class FakeEngine:
    """Stands in for the GriptapeNodes facade, recording the macros it was asked to resolve."""

    def __init__(
        self,
        resolved: str | None,
        missing: set[str] | None = None,
        absolute: str | None = None,
        library_name: str | None = None,
        library_directory: str | None = None,
    ) -> None:
        self._resolved = resolved
        self._missing = missing or {"workspace_dir"}
        # Diverges from resolved_path by default: the engine anchors absolute_path on the
        # workspace, and a fake that returns the same string for both cannot catch code
        # reading the wrong field.
        self._absolute = absolute if absolute is not None else f"/engine/workspace/{resolved}"
        self._library_name = library_name
        self._library_directory = library_directory
        self.requests: list[Any] = []

    def LibraryManager(self) -> FakeLibraryManager:  # noqa: N802
        return FakeLibraryManager(self._library_name)

    def handle_request(self, request: Any) -> Any:
        self.requests.append(request)
        if isinstance(request, GetLibrarySourceInfoRequest):
            if self._library_directory is None:
                return GetPathForMacroResultFailure(
                    failure_reason=PathResolutionFailureReason.MISSING_REQUIRED_VARIABLES,
                    missing_variables=set(),
                    result_details="library not found",
                )
            return GetLibrarySourceInfoResultSuccess(
                library_name=request.library,
                library_json_path=f"{self._library_directory}/griptape-nodes-library.json",
                library_directory=self._library_directory,
                result_details="resolved",
            )
        if self._resolved is None:
            return GetPathForMacroResultFailure(
                failure_reason=PathResolutionFailureReason.MISSING_REQUIRED_VARIABLES,
                missing_variables=self._missing,
                result_details="missing required variables",
            )
        return GetPathForMacroResultSuccess(
            resolved_path=Path(self._resolved),
            absolute_path=Path(self._absolute),
            result_details="resolved",
        )


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    def install(
        resolved: str | None,
        missing: set[str] | None = None,
        absolute: str | None = None,
        library_name: str | None = None,
        library_directory: str | None = None,
    ) -> FakeEngine:
        fake = FakeEngine(resolved, missing, absolute, library_name, library_directory)
        monkeypatch.setattr(script_path_module, "GriptapeNodes", fake)
        return fake

    return install


class TestMacroExpansion:
    def test_a_workspace_macro_becomes_an_absolute_path(self, engine) -> None:  # noqa: ANN001
        engine("/ws/shots/comp.nk")
        resolution = resolve_script_path("{workspace_dir}/shots/comp.nk")
        assert resolution.path == "/ws/shots/comp.nk"
        assert resolution.failure_reason is None

    def test_a_plain_absolute_path_never_reaches_the_engine(self, engine) -> None:  # noqa: ANN001
        fake = engine("/unused")
        resolution = resolve_script_path("/shots/comp.nk")
        assert resolution.path == "/shots/comp.nk"
        assert fake.requests == []

    def test_an_unresolvable_macro_yields_no_path_and_names_the_variable(self, engine) -> None:  # noqa: ANN001
        engine(None, missing={"workspace_dir"})
        resolution = resolve_script_path("{workspace_dir}/shots/comp.nk")
        assert resolution.path is None
        assert resolution.missing_variables == ("workspace_dir",)
        assert "workspace_dir" in describe_failure(resolution)

    def test_malformed_macro_syntax_is_reported_rather_than_used_literally(self, engine) -> None:  # noqa: ANN001
        engine("/unused")
        resolution = resolve_script_path("{unclosed/comp.nk")
        assert resolution.path is None
        assert resolution.failure_reason is not None

    def test_the_raw_text_is_preserved_for_quoting_back(self, engine) -> None:  # noqa: ANN001
        engine(None)
        resolution = resolve_script_path("  {workspace_dir}/comp.nk  ")
        assert resolution.raw_text == "{workspace_dir}/comp.nk"

    def test_empty_text_is_not_a_failure(self, engine) -> None:  # noqa: ANN001
        engine("/unused")
        resolution = resolve_script_path("")
        assert resolution.path is None
        assert resolution.failure_reason is None
        assert "not set" in describe_failure(resolution)


class TestTheEnginesWorkspaceAnchoredPathIsNeverUsed:
    """absolute_path is anchored on the workspace; a library template lives outside it."""

    def test_a_macro_expanding_to_relative_text_anchors_to_the_workflow_not_the_workspace(
        self,
        engine,  # noqa: ANN001
    ) -> None:
        # Reading absolute_path here is the exact bug this resolution exists to avoid: a
        # library template's script would be looked for inside the workspace instead.
        engine("sh010/comp.nk", absolute="/engine/workspace/sh010/comp.nk")
        resolution = resolve_script_path("{shot}/comp.nk", anchor_dir="/library/my_lib")
        assert resolution.path == "/library/my_lib/sh010/comp.nk"
        assert "/engine/workspace" not in (resolution.path or "")

    def test_a_macro_expanding_to_an_absolute_path_ignores_the_anchor(self, engine) -> None:  # noqa: ANN001
        """The primary {workspace_dir} case: resolved_path is already absolute."""
        engine("/ws/comp.nk", absolute="/engine/workspace/ws/comp.nk")
        resolution = resolve_script_path("{workspace_dir}/comp.nk", anchor_dir="/library/my_lib")
        assert resolution.path == "/ws/comp.nk"


class TestDescribeFailure:
    @staticmethod
    def _missing_file(path: str, raw_text: str) -> ScriptPathResolution:
        return ScriptPathResolution(path=path, raw_text=raw_text, failure_reason=None, missing_variables=())

    def test_a_missing_file_is_named_by_the_path_the_node_looked_at(self) -> None:
        message = describe_failure(self._missing_file("/library/my_lib/comp.nk", "{workflow_dir}/comp.nk"))
        assert "/library/my_lib/comp.nk" in message
        assert "not set" not in message

    def test_a_missing_file_is_not_reported_as_the_macro_text(self) -> None:
        message = describe_failure(self._missing_file("/library/my_lib/comp.nk", "{workflow_dir}/comp.nk"))
        assert "{workflow_dir}" not in message


class TestAnchoring:
    def test_a_relative_path_anchors_to_the_workflow_directory(self, engine) -> None:  # noqa: ANN001
        engine("/unused")
        resolution = resolve_script_path("scripts/comp.nk", anchor_dir="/library/my_lib")
        assert resolution.path == "/library/my_lib/scripts/comp.nk"

    def test_an_absolute_path_ignores_the_anchor(self, engine) -> None:  # noqa: ANN001
        engine("/unused")
        resolution = resolve_script_path("/elsewhere/comp.nk", anchor_dir="/library/my_lib")
        assert resolution.path == "/elsewhere/comp.nk"

    def test_a_relative_path_without_an_anchor_stays_relative(self, engine) -> None:  # noqa: ANN001
        engine("/unused")
        resolution = resolve_script_path("comp.nk")
        assert resolution.path == "comp.nk"

    def test_backslashes_are_normalized_for_nuke(self, engine) -> None:  # noqa: ANN001
        engine("/unused")
        resolution = resolve_script_path("sub/../comp.nk", anchor_dir="/lib")
        assert "\\" not in (resolution.path or "")
        assert resolution.path == "/lib/comp.nk"


class TestLazyAnchor:
    """Resolving an anchor costs an engine round-trip, so only a relative path may pay it."""

    @staticmethod
    def _counting_anchor(calls: list[int]):  # noqa: ANN205
        def anchor() -> str | None:
            calls.append(1)
            return "/library/my_lib"

        return anchor

    def test_an_absolute_path_never_resolves_the_anchor(self, engine) -> None:  # noqa: ANN001
        engine("/unused")
        calls: list[int] = []
        resolution = resolve_script_path("/shots/comp.nk", anchor_dir=self._counting_anchor(calls))
        assert resolution.path == "/shots/comp.nk"
        assert calls == []

    def test_empty_text_never_resolves_the_anchor(self, engine) -> None:  # noqa: ANN001
        engine("/unused")
        calls: list[int] = []
        resolve_script_path("", anchor_dir=self._counting_anchor(calls))
        assert calls == []

    def test_a_relative_path_resolves_the_anchor_once(self, engine) -> None:  # noqa: ANN001
        engine("/unused")
        calls: list[int] = []
        resolution = resolve_script_path("scripts/comp.nk", anchor_dir=self._counting_anchor(calls))
        assert resolution.path == "/library/my_lib/scripts/comp.nk"
        assert calls == [1]

    def test_a_callable_anchor_returning_none_leaves_the_path_relative(self, engine) -> None:  # noqa: ANN001
        engine("/unused")
        resolution = resolve_script_path("comp.nk", anchor_dir=lambda: None)
        assert resolution.path == "comp.nk"


class TestLibraryDirToken:
    """{library_dir} anchors a shipped template to its library, surviving SAVE_FROM_TEMPLATE."""

    def test_a_library_dir_token_is_substituted_before_other_macros(self, engine) -> None:  # noqa: ANN001
        engine("/ws/comp.nk", library_name="nuke_lib", library_directory="/library/my_lib")
        resolution = resolve_script_path(
            "{library_dir}/scripts/comp.nk",
            anchor_dir="/engine/workspace",
            library_dir="/library/my_lib",
        )
        assert resolution.path == "/library/my_lib/scripts/comp.nk"

    def test_the_workflow_dir_anchor_is_never_consulted_once_library_dir_resolves(self, engine) -> None:  # noqa: ANN001
        # Simulates post-SAVE_FROM_TEMPLATE: {workflow_dir} now resolves to the workspace,
        # but {library_dir} still finds the library's own folder.
        engine("sh010/comp.nk", library_name="nuke_lib", library_directory="/library/my_lib")
        resolution = resolve_script_path(
            "{library_dir}/comp.nk",
            anchor_dir="/engine/workspace",
            library_dir="/library/my_lib",
        )
        assert resolution.path == "/library/my_lib/comp.nk"
        assert "/engine/workspace" not in (resolution.path or "")

    def test_a_missing_library_dir_leaves_the_token_untouched_and_the_macro_branch_reports_it(
        self,
        engine,  # noqa: ANN001
    ) -> None:
        engine(None, missing={"library_dir"})
        resolution = resolve_script_path("{library_dir}/comp.nk", library_dir=lambda: None)
        assert resolution.path is None
        assert resolution.failure_reason is not None

    def test_library_dir_is_resolved_lazily(self, engine) -> None:  # noqa: ANN001
        engine("/unused")
        calls: list[int] = []

        def lazy_library_dir() -> str:
            calls.append(1)
            return "/library/my_lib"

        resolve_script_path("/shots/comp.nk", library_dir=lazy_library_dir)
        assert calls == []


class TestLibraryDirFunction:
    def test_library_dir_resolves_through_the_owning_library(self, engine) -> None:  # noqa: ANN001
        engine("/unused", library_name="nuke_lib", library_directory="/library/my_lib")
        assert library_dir("NukeScriptNode") == "/library/my_lib"

    def test_library_dir_is_none_when_the_node_type_has_no_library(self, engine) -> None:  # noqa: ANN001
        engine("/unused", library_name=None)
        assert library_dir("NukeScriptNode") is None

    def test_library_dir_is_none_when_the_library_cannot_be_found(self, engine) -> None:  # noqa: ANN001
        engine("/unused", library_name="nuke_lib", library_directory=None)
        assert library_dir("NukeScriptNode") is None


class TestWorkflowAnchorDir:
    def test_the_anchor_is_the_resolved_workflow_directory(self, engine) -> None:  # noqa: ANN001
        fake = engine("/library/my_lib")
        assert workflow_anchor_dir() == "/library/my_lib"
        assert isinstance(fake.requests[0], GetPathForMacroRequest)

    def test_an_unsaved_workflow_has_no_anchor(self, engine) -> None:  # noqa: ANN001
        engine(None)
        assert workflow_anchor_dir() is None

    def test_the_anchor_is_the_workflow_folder_not_its_workspace_twin(self, engine) -> None:  # noqa: ANN001
        engine("/library/my_lib", absolute="/engine/workspace/library/my_lib")
        assert workflow_anchor_dir() == "/library/my_lib"
