"""Tests for nuke_workflow_runner.py: environment bootstrap and output-dir export."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

# See tests/conftest.py for the XDG_CONFIG_HOME guard this import relies on.
import nuke_workflow_runner
import pytest
import register_libraries_script
from griptape_nodes.common.project_templates.directory import DirectoryDefinition
from griptape_nodes.common.project_templates.project import ProjectTemplate
from griptape_nodes.common.project_templates.validation import ProjectValidationInfo, ProjectValidationStatus
from griptape_nodes.retained_mode.events.project_events import (
    GetPathForMacroRequest,
    GetPathForMacroResultFailure,
    GetPathForMacroResultSuccess,
    LoadProjectTemplateRequest,
    LoadProjectTemplateResultFailure,
    LoadProjectTemplateResultSuccess,
    PathResolutionFailureReason,
    SetCurrentProjectRequest,
    SetCurrentProjectResultSuccess,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from publish_gizmo import output_paths

if TYPE_CHECKING:
    from collections.abc import Callable

    from griptape_nodes.retained_mode.events.base_events import ResultPayload


class TestBootstrapEnvironment:
    """Tests for nuke_workflow_runner._bootstrap_environment's workspace/env-var pinning."""

    @pytest.fixture(autouse=True)
    def emit_payload_mock(self, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        """Swap nuke_workflow_runner's os/sys/emit_payload for fakes; return the emit_payload mock for assertions."""
        monkeypatch.setattr(nuke_workflow_runner, "os", types.SimpleNamespace(environ={}))
        monkeypatch.setattr(nuke_workflow_runner, "sys", MagicMock(exit=MagicMock(side_effect=SystemExit)))
        emit_payload = MagicMock()
        # monkeypatch.setattr is properly undone on teardown, unlike monkeypatch.delenv (which
        # records no undo entry for a key that was already absent) -- see
        # test_does_not_leak_into_real_process_environment for the regression this guards against.
        monkeypatch.setattr(nuke_workflow_runner, "emit_payload", emit_payload)
        return emit_payload

    def test_pins_workspace_to_bundle_root(self, emit_payload_mock: MagicMock) -> None:
        """The workspace must be the bundle root, whatever .nk script the run came from."""
        nuke_workflow_runner._bootstrap_environment()

        emit_payload_mock.assert_not_called()
        # The bundled workflow may hold paths relative to the bundle, so the workspace can never
        # follow the artist's .nk script location.
        bundle_root = str(Path(nuke_workflow_runner.__file__).parent)
        assert nuke_workflow_runner.os.environ["GTN_CONFIG_WORKSPACE_DIRECTORY"] == bundle_root

    def test_does_not_leak_into_real_process_environment(self, emit_payload_mock: MagicMock) -> None:
        """Regression guard: the os/sys fakes above must actually replace the module's os, not sit alongside it."""
        before = dict(os.environ)

        nuke_workflow_runner._bootstrap_environment()

        assert os.environ == before, "os.environ was mutated by _bootstrap_environment"


class TestMainArgumentValidation:
    """Tests for the argument checks main() makes before any workflow is loaded."""

    def test_rejects_relative_nk_script_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A relative --nk-script-dir must fail loudly, not silently anchor outputs under the wrong directory."""
        emit_payload = MagicMock()
        monkeypatch.setattr(nuke_workflow_runner, "emit_payload", emit_payload)
        # argparse reads the real sys.argv, so this must be set on the genuine sys module.
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "nuke_workflow_runner.py",
                "--workflow-file",
                "unused_workflow.py",
                "--json-input",
                "{}",
                "--nk-script-dir",
                "relative/nk/dir",
            ],
        )

        with pytest.raises(SystemExit):
            nuke_workflow_runner.main()

        emit_payload.assert_called_once()
        payload = emit_payload.call_args[0][0]
        assert "--nk-script-dir" in payload["error"]
        assert "relative/nk/dir" in payload["error"]


class TestMainOutputSerialization:
    """Tests for how main() serializes the finished run's output values."""

    @pytest.fixture
    def emit_payload(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        mock = Mock(spec=nuke_workflow_runner.emit_payload)
        monkeypatch.setattr(nuke_workflow_runner, "emit_payload", mock)
        return mock

    @pytest.fixture
    def basic_config(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        mock = Mock(spec=logging.basicConfig)
        monkeypatch.setattr(logging, "basicConfig", mock)
        return mock

    @pytest.fixture
    def bootstrap_environment(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        mock = Mock(spec=nuke_workflow_runner._bootstrap_environment)
        monkeypatch.setattr(nuke_workflow_runner, "_bootstrap_environment", mock)
        return mock

    @pytest.fixture
    def activate_bundle_project(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        activation = output_paths.ProjectActivation(succeeded=True, failure_reason=None, engine_detail=None)
        mock = Mock(spec=nuke_workflow_runner._activate_bundle_project, return_value=activation)
        monkeypatch.setattr(nuke_workflow_runner, "_activate_bundle_project", mock)
        return mock

    @pytest.fixture
    def export_outputs_dir(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        mock = Mock(spec=nuke_workflow_runner._export_outputs_dir, return_value=None)
        monkeypatch.setattr(nuke_workflow_runner, "_export_outputs_dir", mock)
        return mock

    @pytest.fixture
    def export_script_dir(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        mock = Mock(spec=nuke_workflow_runner._export_script_dir, return_value="/projects/shot_010/comp")
        monkeypatch.setattr(nuke_workflow_runner, "_export_script_dir", mock)
        return mock

    @pytest.fixture
    def export_engine_config_directories(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        mock = Mock(spec=nuke_workflow_runner._export_engine_config_directories, return_value=None)
        monkeypatch.setattr(nuke_workflow_runner, "_export_engine_config_directories", mock)
        return mock

    @pytest.fixture
    def register_bundled_libraries(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        mock = Mock(spec=register_libraries_script.register_bundled_libraries)
        monkeypatch.setattr(register_libraries_script, "register_bundled_libraries", mock)
        return mock

    @pytest.fixture
    def subprocess_run(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        mock = Mock(spec=subprocess.run)
        monkeypatch.setattr(nuke_workflow_runner.subprocess, "run", mock)
        return mock

    @pytest.fixture
    def load_workflow_module(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        mock = Mock(spec=nuke_workflow_runner._load_workflow_module)
        monkeypatch.setattr(nuke_workflow_runner, "_load_workflow_module", mock)
        return mock

    @pytest.fixture
    def serialize_output(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        mock = Mock(spec=output_paths.serialize_output, return_value={"image": "/renders/gen.png"})
        monkeypatch.setattr(nuke_workflow_runner, "serialize_output", mock)
        return mock

    def test_the_finished_runs_output_is_serialized_and_emitted_verbatim(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        emit_payload: Mock,
        basic_config: Mock,
        bootstrap_environment: Mock,
        activate_bundle_project: Mock,
        export_outputs_dir: Mock,
        export_script_dir: Mock,
        export_engine_config_directories: Mock,
        register_bundled_libraries: Mock,
        subprocess_run: Mock,
        load_workflow_module: Mock,
        serialize_output: Mock,
    ) -> None:
        """Whatever the executor produced is what reaches Nuke; nothing is rewritten on the way out."""
        workflow_file = tmp_path / "workflow.py"
        workflow_file.write_text("", encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_workflow.py",
                "--workflow-file",
                str(workflow_file),
                "--json-input",
                "{}",
                "--nk-script-dir",
                "/projects/shot_010/comp",
            ],
        )

        nuke_workflow_runner.main()

        workflow_output = load_workflow_module.return_value.execute_workflow.return_value
        # Nothing is threaded in alongside the output: the engine substitutes an output parameter's
        # macros as the value is set, so serialization has nothing left to resolve.
        serialize_output.assert_called_once_with(workflow_output)
        emit_payload.assert_called_once_with({"image": "/renders/gen.png"})
        subprocess_run.assert_not_called()
        register_bundled_libraries.assert_called_once_with()

    def test_the_bundles_project_is_made_current_before_the_output_dir_is_resolved(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        emit_payload: Mock,
        basic_config: Mock,
        bootstrap_environment: Mock,
        activate_bundle_project: Mock,
        export_outputs_dir: Mock,
        export_script_dir: Mock,
        export_engine_config_directories: Mock,
        register_bundled_libraries: Mock,
        subprocess_run: Mock,
        load_workflow_module: Mock,
        serialize_output: Mock,
    ) -> None:
        """The knob resolves against whichever project is current, so the bundle's own must be current first."""
        workflow_file = tmp_path / "workflow.py"
        workflow_file.write_text("", encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            ["run_workflow.py", "--workflow-file", str(workflow_file), "--json-input", "{}"],
        )
        call_order = Mock()
        call_order.attach_mock(activate_bundle_project, "activate")
        call_order.attach_mock(export_outputs_dir, "export")

        nuke_workflow_runner.main()

        bundle_dir = Path(nuke_workflow_runner.__file__).parent
        # Activation happens even with the Output Directory knob left blank, as it is here: no
        # project id is passed when the knob is resolved, so the bundle has to be the current
        # project by then whether or not the knob holds a macro.
        activate_bundle_project.assert_called_once_with(bundle_dir / "project.yml")
        export_outputs_dir.assert_called_once_with(None, None, bundle_dir)
        assert [name for name, _args, _kwargs in call_order.mock_calls] == ["activate", "export"]
        emit_payload.assert_called_once_with({"image": "/renders/gen.png"})

    def test_the_script_dir_anchor_is_exported_before_the_bundles_project_is_activated(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        emit_payload: Mock,
        basic_config: Mock,
        bootstrap_environment: Mock,
        activate_bundle_project: Mock,
        export_outputs_dir: Mock,
        export_script_dir: Mock,
        export_engine_config_directories: Mock,
        register_bundled_libraries: Mock,
        subprocess_run: Mock,
        load_workflow_module: Mock,
        serialize_output: Mock,
    ) -> None:
        """Activating the project is the first thing that can resolve a directory macro, so the anchor precedes it.

        Every writable directory in the bundled project.yml is defined in terms of this one
        variable. Exported late, a directory resolved in between carries an unresolved
        ``{GTN_NUKE_GIZMO_SCRIPT_DIR}`` in its path. The config-backed directories go out at the
        same point for a stricter reason: activation is also the first engine call, so their
        values must already be in the environment when the engine reads its config.
        """
        workflow_file = tmp_path / "workflow.py"
        workflow_file.write_text("", encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_workflow.py",
                "--workflow-file",
                str(workflow_file),
                "--json-input",
                "{}",
                "--nk-script-dir",
                "/projects/shot_010/comp",
            ],
        )
        call_order = Mock()
        call_order.attach_mock(export_script_dir, "export_script_dir")
        call_order.attach_mock(export_engine_config_directories, "export_engine_config_directories")
        call_order.attach_mock(activate_bundle_project, "activate")
        call_order.attach_mock(export_outputs_dir, "export_outputs_dir")

        nuke_workflow_runner.main()

        bundle_dir = Path(nuke_workflow_runner.__file__).parent
        export_script_dir.assert_called_once_with("/projects/shot_010/comp", bundle_dir)
        # The anchor the script-dir export computed, not one worked out a second time: the static
        # files directory has to land under the same hidden parent as the project.yml directories.
        export_engine_config_directories.assert_called_once_with(export_script_dir.return_value)
        assert [name for name, _args, _kwargs in call_order.mock_calls] == [
            "export_script_dir",
            "export_engine_config_directories",
            "activate",
            "export_outputs_dir",
        ]


class TestExportOutputsDir:
    """Tests for nuke_workflow_runner._export_outputs_dir's OUTPUTS_DIR_ENV_VAR export."""

    @pytest.fixture(autouse=True)
    def fake_os(self, monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
        """Swap nuke_workflow_runner's os for a fake so env writes are inspectable and don't leak."""
        fake = types.SimpleNamespace(environ={})
        monkeypatch.setattr(nuke_workflow_runner, "os", fake)
        return fake

    def test_blank_output_dir_exports_default_next_to_nk_script(
        self, fake_os: types.SimpleNamespace, tmp_path: Path
    ) -> None:
        """A blank Output Directory knob must export the default '<nk_script_dir>/griptape_outputs'."""
        nk_dir = tmp_path / "nk_shot"
        bundle_dir = tmp_path / "bundle"

        nuke_workflow_runner._export_outputs_dir(None, str(nk_dir), bundle_dir)

        assert fake_os.environ[nuke_workflow_runner.OUTPUTS_DIR_ENV_VAR] == f"{nk_dir}/griptape_outputs"

    def test_blank_output_dir_falls_back_to_bundle_dir_when_nk_script_dir_absent(
        self, fake_os: types.SimpleNamespace, tmp_path: Path
    ) -> None:
        """With no .nk script known yet, the default anchors to the bundle directory instead."""
        bundle_dir = tmp_path / "bundle"

        nuke_workflow_runner._export_outputs_dir(None, None, bundle_dir)

        assert fake_os.environ[nuke_workflow_runner.OUTPUTS_DIR_ENV_VAR] == f"{bundle_dir}/griptape_outputs"

    def test_absolute_output_dir_override_is_exported_verbatim(
        self, fake_os: types.SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A plain absolute --output-dir override must be exported as given (normalized)."""
        nk_dir = tmp_path / "nk_shot"
        bundle_dir = tmp_path / "bundle"
        override_dir = tmp_path / "explicit_renders"
        _fake_macro_resolution(monkeypatch, lambda template: template)

        nuke_workflow_runner._export_outputs_dir(str(override_dir), str(nk_dir), bundle_dir)

        assert fake_os.environ[nuke_workflow_runner.OUTPUTS_DIR_ENV_VAR] == str(override_dir).replace("\\", "/")

    def test_outputs_macro_override_resolves_against_the_default_already_exported(
        self, fake_os: types.SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """'{outputs}/renders' means 'a subfolder of the default location', so the default must be exported first."""
        bundle_dir = tmp_path / "bundle"
        nk_dir = tmp_path / "nk_shot"

        def _expand_outputs(template: str) -> str:
            # Mirrors the bundled project.yml, whose outputs directory is OUTPUTS_DIR_ENV_VAR, so a
            # value read too early shows up as a wrong answer rather than passing silently.
            exported = fake_os.environ[nuke_workflow_runner.OUTPUTS_DIR_ENV_VAR]
            return template.replace("{outputs}", exported)

        handle_request = _fake_macro_resolution(monkeypatch, _expand_outputs)

        nuke_workflow_runner._export_outputs_dir("{outputs}/renders", str(nk_dir), bundle_dir)

        # This is the assertion that catches a reordering of the two OUTPUTS_DIR_ENV_VAR writes:
        # the knob value resolves against the default only if the default was exported first.
        assert fake_os.environ[nuke_workflow_runner.OUTPUTS_DIR_ENV_VAR] == f"{nk_dir}/griptape_outputs/renders"
        handle_request.assert_called_once()

    def test_unresolvable_macro_output_dir_aborts_naming_the_knob_text_and_the_variable(
        self, fake_os: types.SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mistyped Output Directory must stop the run up front, quoting what the artist typed."""
        bundle_dir = tmp_path / "bundle"
        emit_payload = MagicMock()
        monkeypatch.setattr(nuke_workflow_runner, "emit_payload", emit_payload)
        _fake_macro_resolution(monkeypatch, lambda _template: None, missing_variables={"outupts"})

        nk_dir = tmp_path / "nk_shot"
        with pytest.raises(SystemExit):
            nuke_workflow_runner._export_outputs_dir("{outupts}/renders", str(nk_dir), bundle_dir)

        emit_payload.assert_called_once()
        payload = emit_payload.call_args[0][0]
        assert "{outupts}/renders" in payload["error"]
        assert "outupts" in payload["error"]

    def test_abort_message_carries_the_engines_explanation_not_just_its_category(
        self, fake_os: types.SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """'MACRO_RESOLUTION_ERROR' names no cause; only the engine's detail says what the artist must change."""
        bundle_dir = tmp_path / "bundle"
        emit_payload = MagicMock()
        monkeypatch.setattr(nuke_workflow_runner, "emit_payload", emit_payload)
        failure = GetPathForMacroResultFailure(
            failure_reason=PathResolutionFailureReason.MACRO_RESOLUTION_ERROR,
            result_details="builtin variable 'workflow_name' cannot be resolved: no current workflow",
        )
        handle_request = Mock(spec=GriptapeNodes.handle_request, return_value=failure)
        monkeypatch.setattr(output_paths.GriptapeNodes, "handle_request", staticmethod(handle_request))

        with pytest.raises(SystemExit):
            nuke_workflow_runner._export_outputs_dir("{workflow_name}/renders", str(tmp_path / "nk_shot"), bundle_dir)

        payload = emit_payload.call_args[0][0]
        assert "builtin variable 'workflow_name' cannot be resolved: no current workflow" in payload["error"]
        assert PathResolutionFailureReason.MACRO_RESOLUTION_ERROR in payload["error"]

    def test_unresolvable_macro_output_dir_is_never_exported(
        self, fake_os: types.SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bundled project.yml points its outputs directory at this variable, and the engine re-resolves it.

        Brace-bearing text exported here comes back as a FileLoadError naming an engine internal,
        after the workflow has already written a file into a junk folder.
        """
        bundle_dir = tmp_path / "bundle"
        monkeypatch.setattr(nuke_workflow_runner, "emit_payload", MagicMock())
        _fake_macro_resolution(monkeypatch, lambda _template: None, missing_variables={"outupts"})

        nk_dir = tmp_path / "nk_shot"
        with pytest.raises(SystemExit):
            nuke_workflow_runner._export_outputs_dir("{outupts}/renders", str(nk_dir), bundle_dir)

        # The provisional seed stays: it is a real resolvable path, written before the knob is read
        # so that a "{outputs}" inside the knob text has something to resolve against.
        assert fake_os.environ[nuke_workflow_runner.OUTPUTS_DIR_ENV_VAR] == f"{nk_dir}/griptape_outputs"


class TestExportScriptDir:
    """Tests for nuke_workflow_runner._export_script_dir's SCRIPT_DIR_ENV_VAR export."""

    @pytest.fixture(autouse=True)
    def fake_os(self, monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
        """Swap nuke_workflow_runner's os for a fake so env writes are inspectable and don't leak."""
        fake = types.SimpleNamespace(environ={})
        monkeypatch.setattr(nuke_workflow_runner, "os", fake)
        return fake

    def test_the_nk_script_dir_becomes_the_anchor(self, fake_os: types.SimpleNamespace, tmp_path: Path) -> None:
        """The bundle's writable directories hang off the artist's .nk script, not the installed gizmo."""
        nk_dir = tmp_path / "nk_shot"
        bundle_dir = tmp_path / "bundle"

        nuke_workflow_runner._export_script_dir(str(nk_dir), bundle_dir)

        assert fake_os.environ[nuke_workflow_runner.SCRIPT_DIR_ENV_VAR] == str(nk_dir)

    def test_falls_back_to_the_bundle_root_when_the_nk_script_is_unsaved(
        self, fake_os: types.SimpleNamespace, tmp_path: Path
    ) -> None:
        """An unsaved .nk has no directory to sit beside, so the anchor falls back as the outputs default does."""
        bundle_dir = tmp_path / "bundle"

        nuke_workflow_runner._export_script_dir(None, bundle_dir)

        assert fake_os.environ[nuke_workflow_runner.SCRIPT_DIR_ENV_VAR] == str(bundle_dir)

    def test_backslashes_are_normalized_to_forward_slashes(self, fake_os: types.SimpleNamespace) -> None:
        """Nuke's TCL layer treats a backslash as an escape, so a Windows path is mangled unless normalized."""
        nuke_workflow_runner._export_script_dir("C:\\projects\\shot_010\\comp", Path("/unused/bundle"))

        assert fake_os.environ[nuke_workflow_runner.SCRIPT_DIR_ENV_VAR] == "C:/projects/shot_010/comp"

    def test_a_trailing_separator_does_not_survive_into_the_anchor(
        self, fake_os: types.SimpleNamespace, tmp_path: Path
    ) -> None:
        """The bundle joins '/<name>' onto this anchor, so a trailing separator would yield '<dir>//temp'."""
        nk_dir = tmp_path / "nk_shot"

        nuke_workflow_runner._export_script_dir(f"{nk_dir}/", tmp_path / "bundle")

        assert fake_os.environ[nuke_workflow_runner.SCRIPT_DIR_ENV_VAR] == str(nk_dir)

    def test_a_parent_segment_does_not_survive_into_the_anchor(
        self, fake_os: types.SimpleNamespace, tmp_path: Path
    ) -> None:
        """The sibling outputs anchor is normalized off the same argument, so an un-collapsed '..' diverges."""
        nk_dir = tmp_path / "nk_shot"

        nuke_workflow_runner._export_script_dir(f"{nk_dir}/renders/..", tmp_path / "bundle")

        assert fake_os.environ[nuke_workflow_runner.SCRIPT_DIR_ENV_VAR] == str(nk_dir)

    def test_the_anchor_is_returned_for_the_config_directories_to_share(
        self, fake_os: types.SimpleNamespace, tmp_path: Path
    ) -> None:
        """The config-backed directories hang off the same anchor, so it is computed here once and handed on."""
        nk_dir = tmp_path / "nk_shot"

        anchor = nuke_workflow_runner._export_script_dir(str(nk_dir), tmp_path / "bundle")

        assert anchor == fake_os.environ[nuke_workflow_runner.SCRIPT_DIR_ENV_VAR]


class TestExportEngineConfigDirectories:
    """Tests for the two writable directories the engine reads from config, not from project.yml."""

    @pytest.fixture(autouse=True)
    def fake_os(self, monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
        """Swap nuke_workflow_runner's os for a fake so env writes are inspectable and don't leak."""
        fake = types.SimpleNamespace(environ={})
        monkeypatch.setattr(nuke_workflow_runner, "os", fake)
        return fake

    def test_static_files_land_beside_the_nk_script(self, fake_os: types.SimpleNamespace, tmp_path: Path) -> None:
        """No situation override can move these: StaticFilesManager rebuilds the path from this config value."""
        nk_dir = tmp_path / "nk_shot"

        nuke_workflow_runner._export_engine_config_directories(str(nk_dir))

        assert fake_os.environ["GTN_CONFIG_STATIC_FILES_DIRECTORY"] == f"{nk_dir}/.griptape/staticfiles"

    def test_synced_workflows_land_in_a_per_machine_scratch_directory(
        self, fake_os: types.SimpleNamespace, tmp_path: Path
    ) -> None:
        """Cloud-sync scratch a gizmo run never uses, so neither the shot folder nor the bundle may hold it."""
        fake_os.environ["XDG_DATA_HOME"] = str(tmp_path / "data_home")
        nk_dir = tmp_path / "nk_shot"

        nuke_workflow_runner._export_engine_config_directories(str(nk_dir))

        synced = fake_os.environ["GTN_CONFIG_SYNCED_WORKFLOWS_DIRECTORY"]
        assert synced == f"{tmp_path / 'data_home'}/griptape_nodes/gizmo_standalone/synced_workflows"
        assert not Path(synced).is_relative_to(nk_dir), (
            "SyncManager mkdir's this unguarded during Engine.__init__, so anchoring it on the .nk "
            "script scaffolds an empty tree into the artist's shot folder on every run."
        )

    def test_synced_workflows_fall_back_to_the_home_data_directory(
        self, fake_os: types.SimpleNamespace, tmp_path: Path
    ) -> None:
        """XDG_DATA_HOME is unset on a stock Windows or macOS host, where the per-machine guarantee still holds."""
        nuke_workflow_runner._export_engine_config_directories(str(tmp_path / "nk_shot"))

        expected = Path.home() / ".local" / "share" / "griptape_nodes" / "gizmo_standalone" / "synced_workflows"
        assert fake_os.environ["GTN_CONFIG_SYNCED_WORKFLOWS_DIRECTORY"] == str(expected).replace("\\", "/")

    def test_backslashes_are_normalized_to_forward_slashes(self, fake_os: types.SimpleNamespace) -> None:
        """Nuke's TCL layer treats a backslash as an escape, so a Windows path is mangled unless normalized."""
        fake_os.environ["XDG_DATA_HOME"] = "C:\\Users\\artist\\AppData\\Local"

        nuke_workflow_runner._export_engine_config_directories("C:\\projects\\shot_010\\comp")

        assert fake_os.environ["GTN_CONFIG_STATIC_FILES_DIRECTORY"] == "C:/projects/shot_010/comp/.griptape/staticfiles"
        assert (
            fake_os.environ["GTN_CONFIG_SYNCED_WORKFLOWS_DIRECTORY"]
            == "C:/Users/artist/AppData/Local/griptape_nodes/gizmo_standalone/synced_workflows"
        )


class TestActivateBundleProject:
    """Tests for nuke_workflow_runner._activate_bundle_project's make-current-or-abort contract."""

    def test_the_bundles_own_project_is_made_current(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Loading the bundle's project.yml is not enough: every later macro resolves against whichever project is current."""
        bundle_dir = tmp_path / "bundle"
        captured_requests = _seed_activated_bundle_project(bundle_dir, monkeypatch)

        nuke_workflow_runner._activate_bundle_project(bundle_dir / "project.yml")

        activated_project_ids = [
            request.project_id for request in captured_requests if isinstance(request, SetCurrentProjectRequest)
        ]
        assert activated_project_ids == ["bundle-project-id"], (
            "The engine must be switched to the project id returned by loading the bundle's own "
            "project.yml, the same file the workflow later executes against."
        )

    def test_missing_bundle_project_aborts_naming_the_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bundle whose project.yml cannot be activated must abort, naming the bundle."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle_project_file = bundle_dir / "project.yml"
        emit_payload = MagicMock()
        monkeypatch.setattr(nuke_workflow_runner, "emit_payload", emit_payload)

        with pytest.raises(SystemExit):
            nuke_workflow_runner._activate_bundle_project(bundle_project_file)

        emit_payload.assert_called_once()
        payload = emit_payload.call_args[0][0]
        assert str(bundle_project_file) in payload["error"]
        assert "Technical detail" not in payload["error"], (
            "No engine was consulted for a missing file, so the message must not trail an empty note."
        )

    def test_abort_message_carries_the_engines_failure_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Why the bundle was rejected only exists inside the engine's result; it must reach the artist."""
        bundle_dir = tmp_path / "bundle"
        _seed_bundle_project(bundle_dir)
        bundle_project_file = bundle_dir / "project.yml"
        load_failure = LoadProjectTemplateResultFailure(
            result_details="project.yml declares an unknown schema version",
            validation=ProjectValidationInfo(status=ProjectValidationStatus.UNUSABLE),
        )
        monkeypatch.setattr(output_paths.GriptapeNodes, "handle_request", staticmethod(lambda _request: load_failure))
        emit_payload = MagicMock()
        monkeypatch.setattr(nuke_workflow_runner, "emit_payload", emit_payload)

        with pytest.raises(SystemExit):
            nuke_workflow_runner._activate_bundle_project(bundle_project_file)

        payload = emit_payload.call_args[0][0]
        assert "project.yml declares an unknown schema version" in payload["error"]
        assert payload["error"].count(str(bundle_project_file)) == 1, (
            f"The bundle path must be named exactly once, got: {payload['error']}"
        )
        assert payload["error"].endswith("project.yml declares an unknown schema version"), (
            "The engine's unpunctuated detail must come last so it cannot run into another sentence."
        )


def _seed_activated_bundle_project(bundle_dir: Path, monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Give *bundle_dir* a project.yml the engine fake accepts and activates, returning its request log."""
    load_success = _seed_bundle_project(bundle_dir, directory_names=("outputs",))
    captured_requests: list[object] = []

    def _fake_handle_request(request: object) -> object:
        captured_requests.append(request)
        if isinstance(request, LoadProjectTemplateRequest):
            return load_success
        if isinstance(request, SetCurrentProjectRequest):
            return SetCurrentProjectResultSuccess(result_details="ok")
        msg = f"Unexpected request: {request!r}"
        raise AssertionError(msg)

    monkeypatch.setattr(output_paths.GriptapeNodes, "handle_request", staticmethod(_fake_handle_request))
    return captured_requests


def _fake_macro_resolution(
    monkeypatch: pytest.MonkeyPatch,
    resolve: Callable[[str], str | None],
    missing_variables: set[str] | None = None,
) -> Mock:
    """Answer every GetPathForMacroRequest with *resolve* applied to the macro's own text, or a failure for None."""

    def _handle_request(request: GetPathForMacroRequest) -> ResultPayload:
        resolved = resolve(request.parsed_macro.template)
        if resolved is None:
            return GetPathForMacroResultFailure(
                failure_reason=PathResolutionFailureReason.MISSING_REQUIRED_VARIABLES,
                missing_variables=missing_variables or set(),
                result_details="no such variable",
            )
        return GetPathForMacroResultSuccess(
            resolved_path=Path(resolved),
            absolute_path=Path("/the/bundle") / resolved.lstrip("/"),
            result_details="ok",
        )

    mock = Mock(spec=GriptapeNodes.handle_request, side_effect=_handle_request)
    monkeypatch.setattr(output_paths.GriptapeNodes, "handle_request", staticmethod(mock))
    return mock


def _seed_bundle_project(bundle_dir: Path, directory_names: tuple[str, ...] = ()) -> LoadProjectTemplateResultSuccess:
    """Write a project.yml declaring *directory_names* into *bundle_dir* and return the engine fake's load result."""
    bundle_dir.mkdir()
    template = ProjectTemplate(
        project_template_schema_version=ProjectTemplate.LATEST_SCHEMA_VERSION,
        name="bundle_project",
        situations={},
        directories={name: DirectoryDefinition(name=name, path_macro=f"griptape_{name}") for name in directory_names},
    )
    (bundle_dir / "project.yml").write_text(template.to_yaml(), encoding="utf-8")
    return LoadProjectTemplateResultSuccess(
        project_id="bundle-project-id",
        template=template,
        validation=ProjectValidationInfo(status=ProjectValidationStatus.GOOD),
        result_details="ok",
    )
