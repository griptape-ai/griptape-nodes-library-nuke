"""Tests for output_paths — Output Directory resolution and workflow-output serialization."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
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
    SetCurrentProjectResultFailure,
    SetCurrentProjectResultSuccess,
    UnresolvedSequenceSlotBehavior,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.retained_mode.managers.project_manager import ProjectManager

from publish_gizmo import output_paths
from publish_gizmo.output_paths import (
    activate_project,
    default_output_dir,
    resolve_output_dir,
    serialize_output,
)

_NK_DIR = "/projects/shot_010/comp"
_COMPANION = "/library/griptape/my_workflow"


class _FakeUrlArtifact:
    def __init__(self, url: str) -> None:
        self.url = url


class _FakeValueArtifact:
    def __init__(self, value: str | bytes) -> None:
        self.value = value


@pytest.fixture
def project_manager(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Stand in for the engine's ProjectManager so no test touches a real loaded project."""
    manager = Mock(spec=ProjectManager)
    monkeypatch.setattr(output_paths.GriptapeNodes, "ProjectManager", staticmethod(lambda: manager))
    return manager


@pytest.fixture
def handle_request(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Stand in for the engine's request bus, resolving every macro to its own template text.

    Echoing the template is faithful to the engine only because a static segment survives
    resolution byte for byte and the handler returns Path(resolved_string), so a macro-free
    template comes back as itself; a change to either would make this fixture a fiction.
    """

    def _echo_the_template(request: GetPathForMacroRequest) -> GetPathForMacroResultSuccess:
        return _resolved(request.parsed_macro.template)

    mock = Mock(spec=GriptapeNodes.handle_request, side_effect=_echo_the_template)
    monkeypatch.setattr(output_paths.GriptapeNodes, "handle_request", staticmethod(mock))
    return mock


def _resolved(resolved_path: str, absolute_path: str | None = None) -> GetPathForMacroResultSuccess:
    """Build the result a successful GetPathForMacroRequest returns."""
    return GetPathForMacroResultSuccess(
        resolved_path=Path(resolved_path),
        absolute_path=Path(absolute_path if absolute_path is not None else f"/engine/workspace/{resolved_path}"),
        result_details="ok",
    )


class TestResolveOutputDir:
    def test_blank_dir_returns_the_default_outputs_dir(self, handle_request: Mock) -> None:
        """A blank knob is the common case, not an error: it resolves to the default rather than failing."""
        assert resolve_output_dir(None, _NK_DIR, _COMPANION).path == f"{_NK_DIR}/griptape_outputs"
        assert resolve_output_dir("", _NK_DIR, _COMPANION).path == f"{_NK_DIR}/griptape_outputs"
        handle_request.assert_not_called()

    def test_blank_dir_falls_back_to_companion_when_script_unsaved(self, handle_request: Mock) -> None:
        assert resolve_output_dir(None, None, _COMPANION).path == f"{_COMPANION}/griptape_outputs"
        handle_request.assert_not_called()

    def test_success_carries_no_failure_for_the_runner_to_report(self, handle_request: Mock) -> None:
        """The runner aborts on any populated failure field, so a resolved knob must leave them all clear."""
        resolution = resolve_output_dir("{outputs}/renders", _NK_DIR, _COMPANION)

        assert resolution.raw_text is None
        assert resolution.failure_reason is None
        assert resolution.missing_variables == ()

    def test_relative_dir_resolves_against_nk_script_dir(self, handle_request: Mock) -> None:
        assert resolve_output_dir("flibbidy", _NK_DIR, _COMPANION).path == f"{_NK_DIR}/flibbidy"

    def test_relative_dir_falls_back_to_companion_when_script_unsaved(self, handle_request: Mock) -> None:
        assert resolve_output_dir("flibbidy", None, _COMPANION).path == f"{_COMPANION}/flibbidy"

    def test_absolute_dir_is_returned_normalized(self, handle_request: Mock) -> None:
        assert resolve_output_dir("/renders/./out/", _NK_DIR, _COMPANION).path == "/renders/out"

    def test_windows_backslashes_become_forward_slashes(self, handle_request: Mock) -> None:
        assert resolve_output_dir("renders\\v001", _NK_DIR, _COMPANION).path == f"{_NK_DIR}/renders/v001"

    def test_tilde_is_expanded_to_home(self, handle_request: Mock) -> None:
        expected = str(Path.home() / "renders").replace("\\", "/")
        assert resolve_output_dir("~/renders", _NK_DIR, _COMPANION).path == expected

    def test_dot_relative_dir_resolves_against_nk_script_dir(self, handle_request: Mock) -> None:
        assert resolve_output_dir("./renders", _NK_DIR, _COMPANION).path == f"{_NK_DIR}/renders"

    def test_knob_text_is_handed_to_the_engine_parsed_and_against_the_current_project(
        self, handle_request: Mock
    ) -> None:
        """No project id is threaded on, so the knob resolves against whichever project is current."""
        resolve_output_dir("{outputs}/renders", _NK_DIR, _COMPANION)

        handle_request.assert_called_once()
        [request] = handle_request.call_args.args
        assert isinstance(request, GetPathForMacroRequest)
        assert request.parsed_macro.template == "{outputs}/renders"
        assert request.variables == {}
        assert request.project_id is None
        # The write-path contract: a "{###}" the artist typed has no value to bind, and rendering
        # it as bare hashes would produce a directory name that is not a path.
        assert request.unresolved_sequence_slot_behavior is UnresolvedSequenceSlotBehavior.FAIL

    def test_relative_resolved_path_is_anchored_beside_the_nk_script(self, handle_request: Mock) -> None:
        handle_request.side_effect = None
        handle_request.return_value = _resolved("griptape_inputs/renders")

        resolution = resolve_output_dir("{inputs}/renders", _NK_DIR, _COMPANION)

        assert resolution.path == f"{_NK_DIR}/griptape_inputs/renders"

    def test_absolute_resolved_path_is_left_where_the_engine_put_it(self, handle_request: Mock) -> None:
        """Anchoring is unconditional, which is only safe if re-anchoring an absolute path is a no-op."""
        handle_request.side_effect = None
        handle_request.return_value = _resolved(f"{_NK_DIR}/griptape_outputs/renders")

        resolution = resolve_output_dir("{outputs}/renders", _NK_DIR, _COMPANION)

        assert resolution.path == f"{_NK_DIR}/griptape_outputs/renders"

    def test_the_engines_workspace_anchored_path_is_never_used(self, handle_request: Mock) -> None:
        """absolute_path is anchored on workspace_path, which the runner pins to the bundle root."""
        # Reading absolute_path here is the exact bug this resolution exists to avoid: it would
        # write every render inside the installed bundle, which may be shared or read-only.
        handle_request.side_effect = None
        handle_request.return_value = _resolved("renders", absolute_path="/the/bundle/renders")

        resolution = resolve_output_dir("{outputs}/renders", _NK_DIR, _COMPANION)

        assert resolution.path == f"{_NK_DIR}/renders"
        assert "/the/bundle" not in str(resolution.path)

    def test_engine_refusing_to_resolve_reports_the_text_as_typed_and_the_offending_name(
        self, handle_request: Mock
    ) -> None:
        """An unresolvable Output Directory fails the run, so the caller gets what it needs to say why."""
        handle_request.side_effect = None
        handle_request.return_value = GetPathForMacroResultFailure(
            failure_reason=PathResolutionFailureReason.MISSING_REQUIRED_VARIABLES,
            missing_variables={"flibbidy"},
            result_details="no such variable",
        )

        resolution = resolve_output_dir("{flibbidy}/out", _NK_DIR, _COMPANION)

        # No anchored path: an unresolved macro exported as the outputs directory is re-resolved by
        # the engine downstream, failing the run mid-way with a partial write already on disk.
        assert resolution.path is None
        assert resolution.raw_text == "{flibbidy}/out"
        assert resolution.failure_reason is not None
        assert PathResolutionFailureReason.MISSING_REQUIRED_VARIABLES in resolution.failure_reason
        assert resolution.missing_variables == ("flibbidy",)

    def test_engine_failure_detail_reaches_the_artist_alongside_its_category(self, handle_request: Mock) -> None:
        """The category is a bare enum name; only result_details says which name failed and why."""
        handle_request.side_effect = None
        handle_request.return_value = GetPathForMacroResultFailure(
            failure_reason=PathResolutionFailureReason.MACRO_RESOLUTION_ERROR,
            result_details="builtin variable 'workflow_name' cannot be resolved: no current workflow",
        )

        resolution = resolve_output_dir("{workflow_name}/out", _NK_DIR, _COMPANION)

        assert resolution.failure_reason is not None
        assert PathResolutionFailureReason.MACRO_RESOLUTION_ERROR in resolution.failure_reason
        assert "builtin variable 'workflow_name' cannot be resolved: no current workflow" in resolution.failure_reason

    def test_one_unknown_name_fails_the_whole_value(self, handle_request: Mock) -> None:
        """A refused request fails the whole knob, including the names that would have resolved.

        Only this module's handling of a failure result is pinned here; that the engine really does
        refuse the whole request rather than resolving what it can is an engine property, covered by
        test_one_unknown_name_in_the_output_dir_stops_the_run_before_anything_is_written in
        tests/integration/test_canary_bundle.py.
        """
        handle_request.side_effect = None
        handle_request.return_value = GetPathForMacroResultFailure(
            failure_reason=PathResolutionFailureReason.MISSING_REQUIRED_VARIABLES,
            missing_variables={"flibbidy"},
            result_details="no such variable",
        )

        resolution = resolve_output_dir("{outputs}/{flibbidy}", _NK_DIR, _COMPANION)

        # The hand-rolled substitution this replaced worked per token, so a typo only misnamed the
        # leaf directory; the engine refuses the whole value instead. Deliberate: one authority on
        # macro resolution is worth more than a partial result nobody asked for.
        assert resolution.path is None
        assert resolution.raw_text == "{outputs}/{flibbidy}"

    def test_engine_refusing_to_resolve_is_reported_at_warning_with_its_reason(
        self, caplog: pytest.LogCaptureFixture, handle_request: Mock
    ) -> None:
        """The abort message goes to Nuke over stdout, so the log still needs its own record of why."""
        handle_request.side_effect = None
        handle_request.return_value = GetPathForMacroResultFailure(
            failure_reason=PathResolutionFailureReason.MISSING_REQUIRED_VARIABLES,
            missing_variables={"flibbidy"},
            result_details="no such variable",
        )

        with caplog.at_level(logging.WARNING):
            resolve_output_dir("{flibbidy}/out", _NK_DIR, _COMPANION)

        assert "{flibbidy}/out" in caplog.text
        assert PathResolutionFailureReason.MISSING_REQUIRED_VARIABLES in caplog.text

    def test_malformed_macro_fails_without_reaching_the_engine(self, handle_request: Mock) -> None:
        """A value the grammar cannot parse never reaches the engine, so the parser's own message is the reason."""
        resolution = resolve_output_dir("{unterminated", _NK_DIR, _COMPANION)

        assert resolution.path is None
        assert resolution.raw_text == "{unterminated"
        assert resolution.failure_reason is not None
        assert "Unclosed brace" in resolution.failure_reason
        assert resolution.missing_variables == ()
        handle_request.assert_not_called()

    def test_malformed_macro_is_reported_at_warning(
        self, caplog: pytest.LogCaptureFixture, handle_request: Mock
    ) -> None:
        with caplog.at_level(logging.WARNING):
            resolve_output_dir("{unclosed", _NK_DIR, _COMPANION)

        assert "Unclosed brace" in caplog.text
        assert "{unclosed" in caplog.text


class TestDefaultOutputDir:
    """The one definition of where outputs land with the knob left blank, shared by the runner's seed."""

    def test_default_sits_next_to_the_nk_script(self) -> None:
        assert default_output_dir(_NK_DIR, _COMPANION) == f"{_NK_DIR}/griptape_outputs"

    def test_default_falls_back_to_the_companion_dir_when_script_unsaved(self) -> None:
        """An unsaved .nk script has no directory to sit beside, so the bundle root takes over."""
        assert default_output_dir(None, _COMPANION) == f"{_COMPANION}/griptape_outputs"

    def test_default_uses_the_shared_outputs_dir_name(self) -> None:
        assert default_output_dir(_NK_DIR, _COMPANION).endswith(f"/{output_paths.OUTPUTS_DIR_NAME}")


class TestNoProjectTemplateParsing:
    """This module is copied verbatim into every artist's gizmo bundle, so it must carry no dead code."""

    # Nothing at runtime parses a project.yml here: the runner goes through activate_project, and
    # the publisher imports the engine's loader directly.
    def test_module_exposes_no_project_template_loader(self) -> None:
        assert not hasattr(output_paths, "load_project_template")

    def test_module_does_not_import_the_yaml_template_loader(self) -> None:
        assert not hasattr(output_paths, "load_project_template_from_yaml")


class TestActivateProject:
    """Each failure must come back with a reason the runner can put in front of the artist."""

    # The reason and the engine's raw wording stay in separate fields so the runner can compose
    # complete sentences; pre-concatenating them produced a run-on with the engine's own
    # "Attempted to.../Failed because..." nested inside the runner's. Nothing is logged here
    # either, since the caller aborts and reports the reason itself.

    def test_missing_project_yml_reports_a_reason_with_no_engine_detail(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No engine was consulted, so there is no engine detail to trail the message with."""
        project_yml = tmp_path / "project.yml"

        with caplog.at_level(logging.WARNING):
            activation = activate_project(project_yml)

        assert activation.succeeded is False
        assert activation.failure_reason is not None
        assert activation.engine_detail is None
        assert str(project_yml) not in activation.failure_reason, (
            "The runner names the bundle path itself; repeating it here prints it twice."
        )
        assert caplog.text == ""

    def test_load_failure_reports_the_engines_own_detail(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_project_yml(tmp_path, "griptape_outputs")
        project_yml = tmp_path / "project.yml"

        failure = LoadProjectTemplateResultFailure(
            result_details="boom",
            validation=ProjectValidationInfo(status=ProjectValidationStatus.UNUSABLE),
        )
        monkeypatch.setattr(output_paths.GriptapeNodes, "handle_request", staticmethod(lambda _request: failure))

        with caplog.at_level(logging.WARNING):
            activation = activate_project(project_yml)

        assert activation.succeeded is False
        assert activation.failure_reason is not None
        assert activation.engine_detail == "boom", (
            "The engine's own explanation is the only thing that says WHY the bundle was rejected; "
            "discarding it leaves the artist with nothing to act on."
        )
        assert "boom" not in activation.failure_reason, (
            "The engine's wording belongs in engine_detail, not spliced into the artist's sentence."
        )
        assert str(project_yml) not in activation.failure_reason
        assert caplog.text == ""

    def test_activation_failure_reports_the_engines_own_detail(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_project_yml(tmp_path, "griptape_outputs")
        project_yml = tmp_path / "project.yml"
        load_success = _load_success("loaded-project-id")
        activation_failure = SetCurrentProjectResultFailure(result_details="boom")

        def _fake_handle_request(request: object) -> object:
            if isinstance(request, LoadProjectTemplateRequest):
                return load_success
            return activation_failure

        monkeypatch.setattr(output_paths.GriptapeNodes, "handle_request", staticmethod(_fake_handle_request))

        with caplog.at_level(logging.WARNING):
            activation = activate_project(project_yml)

        assert activation.succeeded is False
        assert activation.failure_reason is not None
        assert activation.engine_detail == "boom"
        assert "boom" not in activation.failure_reason
        assert str(project_yml) not in activation.failure_reason
        assert caplog.text == ""

    def test_success_activates_the_loaded_project_and_reports_no_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The project the engine is switched to must be the one just loaded from the bundle."""
        _write_project_yml(tmp_path, "griptape_outputs")
        project_yml = tmp_path / "project.yml"
        load_success = _load_success("loaded-project-id")
        captured_requests: list[object] = []

        def _fake_handle_request(request: object) -> object:
            captured_requests.append(request)
            if isinstance(request, LoadProjectTemplateRequest):
                return load_success
            return SetCurrentProjectResultSuccess(result_details="ok")

        monkeypatch.setattr(output_paths.GriptapeNodes, "handle_request", staticmethod(_fake_handle_request))

        activation = activate_project(project_yml)

        assert activation.succeeded is True
        assert activation.failure_reason is None
        assert activation.engine_detail is None
        activation_requests = [r for r in captured_requests if isinstance(r, SetCurrentProjectRequest)]
        assert len(activation_requests) == 1
        assert activation_requests[0].project_id == "loaded-project-id"


class TestSerializeOutput:
    def test_empty_output_yields_empty_dict(self) -> None:
        assert serialize_output(None) == {}
        assert serialize_output({}) == {}

    def test_none_parameter_value_becomes_empty_string(self) -> None:
        assert serialize_output({"Node": {"caption": None}}) == {"caption": ""}

    def test_unix_file_uri_keeps_leading_slash(self) -> None:
        output = {"Node": {"image": _FakeUrlArtifact("file:///renders/gen.png")}}
        assert serialize_output(output) == {"image": "/renders/gen.png"}

    def test_windows_file_uri_drops_slash_before_drive_letter(self) -> None:
        output = {"Node": {"image": _FakeUrlArtifact("file:///C:/renders/gen.png")}}
        assert serialize_output(output) == {"image": "C:/renders/gen.png"}

    def test_non_file_url_is_passed_through_verbatim(self) -> None:
        """Only a file:// URI names something on disk; anything else is Nuke's problem, not ours to rewrite."""
        output = {"Node": {"image": _FakeUrlArtifact("https://example.invalid/renders/gen.png")}}
        assert serialize_output(output) == {"image": "https://example.invalid/renders/gen.png"}

    def test_binary_artifact_value_is_summarized(self) -> None:
        output = {"Node": {"blob": _FakeValueArtifact(b"1234")}}
        assert serialize_output(output) == {"blob": "<binary 4 bytes>"}

    def test_plain_value_is_stringified(self) -> None:
        assert serialize_output({"Node": {"path": "/renders/out.exr", "count": 3}}) == {
            "path": "/renders/out.exr",
            "count": "3",
        }

    def test_non_dict_node_entry_is_skipped(self) -> None:
        assert serialize_output({"Node": "not a dict"}) == {}

    def test_empty_output_value_stays_empty_rather_than_becoming_a_dot(self) -> None:
        """Path("") is ".": pushing an output value through pathlib would invent a directory reference."""
        output = {"Node": {"caption": _FakeValueArtifact("")}}

        assert serialize_output(output) == {"caption": ""}

    def test_prose_naming_an_environment_variable_is_returned_byte_identical(
        self, caplog: pytest.LogCaptureFixture, project_manager: Mock, handle_request: Mock
    ) -> None:
        """Model prose is not a path: a name the engine already declined to substitute survives untouched."""
        prose = "I wrote the frames to {HOME}/renders, as you asked."
        output = {"Node": {"summary": _FakeValueArtifact(prose)}}

        with caplog.at_level(logging.WARNING):
            assert serialize_output(output) == {"summary": prose}

        # Brace-bearing free text is expected, not a problem worth putting in front of the artist.
        assert caplog.text == ""
        # These, not the equality above, are what catch substitution being reintroduced here, by
        # either route it could arrive on -- the manager called directly, or a macro request put on
        # the engine's bus. The engine already substitutes output parameter values upstream, so a
        # second pass over them can only paste in something it deliberately left alone.
        project_manager.resolve_project_variable.assert_not_called()
        handle_request.assert_not_called()

    def test_credential_named_in_output_text_is_never_substituted(
        self, monkeypatch: pytest.MonkeyPatch, project_manager: Mock, handle_request: Mock
    ) -> None:
        """The bundled .env is loaded into this process, so an echoed {GT_CLOUD_API_KEY} could leak a key into a knob."""
        monkeypatch.setenv("GT_CLOUD_API_KEY", "sk-super-secret")
        output = {"Node": {"echo": _FakeValueArtifact("my key is {GT_CLOUD_API_KEY}")}}

        result = serialize_output(output)

        assert result == {"echo": "my key is {GT_CLOUD_API_KEY}"}
        assert "sk-super-secret" not in result["echo"]
        # These, not the equality above, are what catch substitution being reintroduced here, by
        # either route it could arrive on -- the manager called directly, or a macro request put on
        # the engine's bus. Resolution inside the engine falls back to this process's environment,
        # which carries the bundled .env, credentials included.
        project_manager.resolve_project_variable.assert_not_called()
        handle_request.assert_not_called()


def _load_success(project_id: str) -> LoadProjectTemplateResultSuccess:
    """Build the result a successful LoadProjectTemplateRequest returns for *project_id*."""
    template = ProjectTemplate(
        project_template_schema_version=ProjectTemplate.LATEST_SCHEMA_VERSION,
        name="test_project",
        situations={},
        directories={
            "outputs": DirectoryDefinition(name="outputs", path_macro="griptape_outputs"),
            "inputs": DirectoryDefinition(name="inputs", path_macro="griptape_inputs"),
        },
    )
    return LoadProjectTemplateResultSuccess(
        project_id=project_id,
        template=template,
        validation=ProjectValidationInfo(status=ProjectValidationStatus.GOOD),
        result_details="ok",
    )


def _write_project_yml(bundle_dir: Path, outputs_path_macro: str) -> None:
    template = ProjectTemplate(
        project_template_schema_version=ProjectTemplate.LATEST_SCHEMA_VERSION,
        name="test_project",
        situations={},
        directories={"outputs": DirectoryDefinition(name="outputs", path_macro=outputs_path_macro)},
    )
    (bundle_dir / "project.yml").write_text(template.to_yaml(), encoding="utf-8")
