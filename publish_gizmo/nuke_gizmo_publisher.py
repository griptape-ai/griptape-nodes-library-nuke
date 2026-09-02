from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from griptape_nodes.common.project_templates.directory import DirectoryDefinition
from griptape_nodes.common.project_templates.loader import load_project_template_from_yaml
from griptape_nodes.common.project_templates.situation import (
    SituationFilePolicy,
    SituationPolicy,
    SituationTemplate,
)
from griptape_nodes.common.project_templates.validation import (
    ProjectValidationInfo,
    ProjectValidationStatus,
)
from griptape_nodes.node_library.workflow_registry import WorkflowRegistry
from griptape_nodes.retained_mode.events.flow_events import GetTopLevelFlowRequest, GetTopLevelFlowResultSuccess
from griptape_nodes.retained_mode.events.os_events import (
    CopyFileRequest,
    CopyFileResultSuccess,
    ReadFileRequest,
    ReadFileResultSuccess,
    WriteFileRequest,
    WriteFileResultSuccess,
)
from griptape_nodes.retained_mode.events.workflow_events import (
    PublishWorkflowResultFailure,
    PublishWorkflowResultSuccess,
    SaveWorkflowRequest,
    SaveWorkflowResultSuccess,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.retained_mode.publishing import WorkflowPackager

from publish_gizmo.constants import (
    BUNDLED_SCRIPTS,
    GRIPTAPE_DIR_NAME,
    GRIPTAPE_RUN_DIR_NAME,
    INIT_MARKER,
    PRESERVED_ON_REPUBLISH,
    versioned_gizmo_filename,
)
from publish_gizmo.nuke_discovery import GIZMO_INSTALL_CUSTOM
from publish_gizmo.nuke_gizmo_builder import NukeGizmoBuilder
from publish_gizmo.output_paths import absolutize

if TYPE_CHECKING:
    from griptape_nodes.node_library.workflow_registry import Workflow
    from griptape_nodes.retained_mode.events.base_events import ResultPayload

logger = logging.getLogger(__name__)

# Env var used to redirect `{outputs}` path macro, configured in project.yml. The
# runner calculates and exports this before executing the workflow.
OUTPUTS_DIR_ENV_VAR = "GTN_NUKE_GIZMO_OUTPUTS_DIR"

# Env var every other writable directory in project.yml is anchored on. The runner
# exports it as the artist's .nk script directory, so one variable moves them all off
# the installed gizmo.
SCRIPT_DIR_ENV_VAR = "GTN_NUKE_GIZMO_SCRIPT_DIR"

# Template directory name -> path relative to SCRIPT_DIR_ENV_VAR. All these intermediate
# writeable directories are gathered under one hidden `.griptape` parent instead of
# scattered beside the .nk script.
SCRIPT_ANCHORED_DIRECTORIES = {
    "backups": f"{GRIPTAPE_RUN_DIR_NAME}/backups",
    "workflow_run_failures": f"{GRIPTAPE_RUN_DIR_NAME}/workflow_run_failures",
    "temp": f"{GRIPTAPE_RUN_DIR_NAME}/temp",
    "griptape-nodes-previews": f"{GRIPTAPE_RUN_DIR_NAME}/previews",
    "griptape-nodes-metadata": f"{GRIPTAPE_RUN_DIR_NAME}/metadata",
    "griptape-nodes-thumbnails": f"{GRIPTAPE_RUN_DIR_NAME}/thumbnails",
}


class NukeGizmoPublisher:
    def __init__(self, workflow_name: str, metadata: dict | None = None) -> None:
        self._workflow_name = workflow_name
        self._metadata: dict = metadata or {}
        self._packager = WorkflowPackager(workflow_name)

    def publish_workflow(self) -> ResultPayload:
        try:
            self._packager.emit_progress(5.0, "Validating workflow...")
            errors = self._validate()
            if errors:
                return PublishWorkflowResultFailure(result_details="\n".join(str(e) for e in errors))

            self._packager.emit_progress(5.0, "Extracting workflow shape...")
            workflow_shape = GriptapeNodes.WorkflowManager().extract_workflow_shape(self._workflow_name)
            self._overlay_current_values(workflow_shape)
            logger.info("Workflow shape: %s", workflow_shape)

            self._packager.emit_progress(5.0, "Saving workflow...")
            workflow = WorkflowRegistry.get_workflow_by_name(self._workflow_name)
            if not workflow.file_path:
                return PublishWorkflowResultFailure(result_details="Workflow has no file path; save it first.")
            save_result = GriptapeNodes.handle_request(SaveWorkflowRequest(file_name=Path(workflow.file_path).stem))
            if not isinstance(save_result, SaveWorkflowResultSuccess):
                return PublishWorkflowResultFailure(result_details="Failed to save workflow before packaging.")

            self._packager.emit_progress(5.0, "Packaging workflow bundle...")
            install_dir = self._resolve_gizmo_install_path()
            if install_dir is None:
                msg = "Gizmo install path is not set."
                raise ValueError(msg)
            # Checked before anything writes: the staging mkdir and every WriteFileRequest
            # create parents, so by the time the publish finishes the directory exists
            # either way and there is no telling afterwards whether we made it.
            install_dir_created = not install_dir.exists()

            workflow_file_path = Path(WorkflowRegistry.get_complete_file_path(workflow.file_path))
            workflow_stem = workflow_file_path.stem

            # All griptape artifacts live under a single subdirectory of the install dir
            griptape_dir = install_dir / GRIPTAPE_DIR_NAME
            companion_base = griptape_dir / workflow_stem

            version = self._determine_version(companion_base)

            # Build the whole bundle in a staging directory that replaces companion_base
            # only once every step has succeeded.  Writing straight into a persistent
            # companion_base accumulates: each writer decides for itself whether it
            # overwrites, so a re-publish can add and update artifacts but never remove
            # one, and a publish that fails partway leaves a half-updated bundle.
            with self._packager.staged_publish(companion_base, preserve=PRESERVED_ON_REPUBLISH) as staging_base:
                dest_workflow, lock_error = self._build_bundle(staging_base, workflow, workflow_file_path, version)

            available_versions = self._collect_versions(companion_base)
            # The gizmo records the final bundle path, not the staging one it was built in.
            dest_workflow = companion_base / dest_workflow.relative_to(staging_base)

            # Generate the versioned gizmo (flat in griptape_dir, not inside companion)
            self._packager.emit_progress(10.0, "Generating gizmo...")
            builder = NukeGizmoBuilder(
                workflow_name=workflow_stem,
                workflow_shape=workflow_shape,
                companion_dir=str(companion_base),
                workflow_file=str(dest_workflow),
                available_versions=available_versions,
                current_version=version,
            )
            gizmo_path = griptape_dir / versioned_gizmo_filename(workflow_stem, version)
            write_result = GriptapeNodes.handle_request(
                WriteFileRequest(file_path=str(gizmo_path), content=builder.generate(), encoding="utf-8")
            )
            if not isinstance(write_result, WriteFileResultSuccess):
                msg = f"Failed to write gizmo to '{gizmo_path}'."
                raise TypeError(msg)
            logger.info("Gizmo written to: %s", gizmo_path)

            # One-time plugin path setup + regenerate menu
            self._ensure_init_plugin_path(install_dir)
            self._regenerate_menu_py(griptape_dir)

            self._save_publish_config(gizmo_path, version)

            self._packager.emit_progress(10.0, "Gizmo installed successfully!")
            details = f"Gizmo v{version} installed to: {gizmo_path}"
            if install_dir_created:
                # A typo'd or accidentally workspace-relative pick now silently becomes a
                # real directory; saying so is the only thing standing between that and a
                # gizmo the artist cannot find.
                details += f"\n\nNote: the install directory did not exist and was created: {install_dir}"
            if lock_error:
                # Surface the skipped lock in the publish result, not just the log:
                # without it the artist running the gizmo is the first to find out.
                details += (
                    f"\n\nWarning: dependencies were not pinned ({lock_error}). "
                    "The gizmo will resolve them on the machine that runs it, which is slower "
                    "and may pick up different versions. Install uv and re-publish to pin them."
                )
            return PublishWorkflowResultSuccess(
                published_workflow_file_path=str(gizmo_path),
                skip_published_workflow_registration=True,
                result_details=details,
            )
        except Exception as e:
            logger.exception("Failed to publish workflow '%s'", self._workflow_name)
            return PublishWorkflowResultFailure(result_details=f"Failed to publish workflow: {e}")

    @staticmethod
    def _overlay_current_values(workflow_shape: dict) -> None:
        """Replace declared defaults in *workflow_shape* with the values set on the canvas.

        ``extract_workflow_shape`` reports ``Parameter.default_value`` and never consults
        ``node.parameter_values``. Every NukeStartFlow input is a user-added parameter whose
        declared default is None, so the value the artist typed lives only in
        ``parameter_values`` — without this the gizmo's knobs are built with no value line
        and Nuke initializes them to 0 / empty, which run_button.py then sends back as a
        real input and writes over the value the bundled workflow saved correctly.

        A path baked from this machine may not resolve on the machine that runs the gizmo;
        the per-knob Link button is how an artist repoints one.
        """
        node_manager = GriptapeNodes.NodeManager()
        for node_name, params in workflow_shape.get("input", {}).items():
            try:
                node = node_manager.get_node_by_name(node_name)
            except Exception:  # noqa: BLE001
                logger.debug("Could not resolve node '%s' for value overlay; keeping declared defaults", node_name)
                continue
            for param_name, info in params.items():
                # Only params the artist actually set; an untouched one keeps its
                # declared default, which is already right.
                if param_name not in node.parameter_values:
                    continue
                try:
                    info["default_value"] = node.get_parameter_value(param_name)
                except Exception:  # noqa: BLE001
                    logger.debug("Could not read '%s.%s' for value overlay", node_name, param_name)

    # -- Bundle assembly --

    def _build_bundle(
        self, companion_base: Path, workflow: Workflow, workflow_file_path: Path, version: int
    ) -> tuple[Path, str | None]:
        """Write the full companion bundle into *companion_base*, returning the workflow path and lock reason.

        Every step raises on failure so the caller's staging directory is discarded and
        the previously published bundle is left in place. Locking is the exception: it
        is best-effort, so its failure reason is returned for the caller to report.
        """
        version_dir = companion_base / f"v{version}"
        version_dir.mkdir(parents=True, exist_ok=True)

        # Package shared files (libraries, config, .env, pyproject.toml) into companion base.
        self._packager.package_to_folder(companion_base, workflow)

        # Generate a uv.lock so the shared companion carries a pinned lockfile.
        # When one is present the gizmo runs frozen, so uv never writes back to
        # the (possibly read-only) shared drive.
        self._packager.emit_progress(5.0, "Locking dependencies...")
        lock_error = self._write_lockfile(companion_base)

        # Override the bundled project.yml with Nuke-specific output conventions
        # so outputs land next to the .nk file, not inside the companion bundle.
        self._customize_project_yml(companion_base)

        # Move the workflow file from companion base into the version subdir.
        # Use copy+delete instead of rename so re-publishing over an existing
        # version (where dest already exists) succeeds without error.
        src_workflow = companion_base / workflow_file_path.name
        dest_workflow = version_dir / workflow_file_path.name
        if src_workflow.exists():
            self._copy_file(src_workflow, dest_workflow, overwrite=True)
            src_workflow.unlink()

        # Copy the runner and button scripts (shared, overwrite on each publish)
        self._packager.emit_progress(5.0, "Writing runner script...")
        for script_name, bundled_name in BUNDLED_SCRIPTS.items():
            self._copy_file(
                Path(__file__).parent / script_name,
                companion_base / bundled_name,
                overwrite=True,
            )

        return dest_workflow, lock_error

    # -- Dependency locking --

    @staticmethod
    def _find_uv() -> str | None:
        """Locate the uv binary, falling back to the paths run_button.py installs into."""
        uv = shutil.which("uv")
        if uv:
            return uv
        ext = ".exe" if platform.system() == "Windows" else ""
        # The engine process may not inherit the shell PATH that has uv on it
        # (notably a GUI-launched app on macOS), so check the known install dirs.
        candidates = [
            Path.home() / ".local" / "share" / "griptape_nodes" / "bin" / f"uv{ext}",
            Path.home() / ".local" / "bin" / f"uv{ext}",
            Path.home() / ".cargo" / "bin" / f"uv{ext}",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    @classmethod
    def _write_lockfile(cls, companion_base: Path) -> str | None:
        """Generate a uv.lock in the companion; return a reason string on failure.

        Best-effort: a missing uv or a lock failure is never fatal to publishing —
        the gizmo resolves deps at run time when no lock ships. The reason is
        returned so the publish result can say so instead of only logging it.
        """
        uv = cls._find_uv()
        if not uv:
            reason = "uv not found on PATH"
            logger.warning("%s; skipping uv.lock generation. Gizmo will resolve deps at run time.", reason)
            return reason
        try:
            result = subprocess.run(  # noqa: S603
                [uv, "lock", "--project", str(companion_base)],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as err:
            logger.warning("uv lock failed (%s); gizmo will resolve deps at run time.", err)
            return f"uv lock failed: {err}"
        if result.returncode != 0:
            logger.warning(
                "uv lock exited %d; gizmo will resolve deps at run time.\n%s", result.returncode, result.stderr
            )
            return f"uv lock exited {result.returncode}"
        if not (companion_base / "uv.lock").is_file():
            # uv can exit 0 without producing a lock next to the project (e.g. an
            # inherited UV_* setting redirecting it), and the run button keys off
            # the file's presence, so verify rather than trust the exit code.
            reason = "uv lock reported success but no uv.lock was written"
            logger.warning("%s; gizmo will resolve deps at run time.", reason)
            return reason
        return None

    # -- File copy helpers --

    @classmethod
    def _copy_file(cls, source_path: str | Path, destination_path: str | Path, *, overwrite: bool = False) -> None:
        """Copies a file from source to destination using OS events for cross-platform compatibility."""
        copy_file_result = GriptapeNodes.handle_request(
            CopyFileRequest(
                source_path=str(source_path),
                destination_path=str(destination_path),
                overwrite=overwrite,
            )
        )
        if not isinstance(copy_file_result, CopyFileResultSuccess):
            details = f"Failed to copy file from '{source_path}' to '{destination_path}'."
            logger.error(details)
            raise TypeError(details)

    # -- Project template customisation --

    @staticmethod
    def _customize_project_yml(companion_base: Path) -> None:
        """Override the bundled project.yml with Nuke-specific output conventions.

        * ``outputs`` directory's ``path_macro`` is the plain, single-token
          ``{OUTPUTS_DIR_ENV_VAR}``: the runner always exports that variable.
        * ``inputs`` is re-anchored on ``{workspace_dir}``, the bundle root, so that a
           bundled static file is read back from where the packager put it; see the
           comment below.
        * Every directory in ``SCRIPT_ANCHORED_DIRECTORIES`` is re-anchored on
          ``{SCRIPT_DIR_ENV_VAR}`` and gathered under the hidden ``.griptape`` parent
          named there, because each of those defaults resolves inside the installed
          gizmo -- possibly a shared or read-only drive.
        * ``save_node_output`` uses a versioned naming convention so each gizmo
          run produces a new numbered file Nuke can detect and load:
          ``{outputs}/{sub_dirs?:/}{file_name_base}{####?:^_v}.{file_extension}``
          ``{sub_dirs?:/}`` passes through any relative subdirectory; when absent
          the whole token (including its separator) is dropped.
          ``CREATE_NEW`` collision policy auto-increments the index on each run.
        * Six further situations are overridden. Five of them -- ``save_file``,
          ``save_workflow``, ``create_versioned_workflow``, ``copy_external_file`` and
          ``download_url`` -- are moved beside the .nk script, under the same hidden
          ``.griptape`` parent, keeping their descriptions and policies: their defaults are
          either relative (so the engine anchors them on the bundle) or explicitly
          bundle-anchored, and the installed gizmo may be shared or read-only.
        * ``save_static_file`` is the sixth, and is the one situation this method does not
          move: its macro carries no anchor at all, because the runner redirects static
          files through the ``static_files_directory`` config value instead -- see
          ``_export_engine_config_directories`` in nuke_workflow_runner.py, and the comment
          above the override itself.

        Fatal on failure. project.yml governs where a run's outputs land, so a bundle
        carrying the engine's un-customized template writes them inside the companion
        instead of next to the .nk file. Returning quietly was survivable when the
        previous publish's customized file stayed behind; a rebuilt bundle has no
        earlier version to fall back on.
        """
        project_yml = companion_base / "project.yml"
        read_result = GriptapeNodes.handle_request(
            ReadFileRequest(file_path=str(project_yml), workspace_only=False, encoding="utf-8")
        )
        if not isinstance(read_result, ReadFileResultSuccess) or not isinstance(read_result.content, str):
            msg = f"Failed to read the bundled project.yml at '{project_yml}'."
            logger.error(msg)
            raise TypeError(msg)

        validation_info = ProjectValidationInfo(status=ProjectValidationStatus.GOOD)
        template = load_project_template_from_yaml(read_result.content, validation_info)
        if template is None:
            msg = f"Failed to parse the bundled project.yml at '{project_yml}'."
            logger.error(msg)
            raise TypeError(msg)

        template.directories["outputs"] = DirectoryDefinition(
            name="outputs",
            path_macro=f"{{{OUTPUTS_DIR_ENV_VAR}}}",
        )

        # `inputs` must resolve to `<bundle>/inputs`, where
        # WorkflowPackager.copy_static_files put the bundled assets.
        template.directories["inputs"] = DirectoryDefinition(
            name="inputs",
            path_macro="{workspace_dir}/inputs",
        )

        for name, relative_path in SCRIPT_ANCHORED_DIRECTORIES.items():
            template.directories[name] = DirectoryDefinition(
                name=name,
                path_macro=f"{{{SCRIPT_DIR_ENV_VAR}}}/{relative_path}",
            )

        template.situations["save_node_output"] = SituationTemplate(
            name="save_node_output",
            description="Node generates and saves output (Nuke gizmo)",
            # No workflow-name subdirectory: files land directly under {outputs}.
            # When Output Directory is set at runtime, {outputs} is redirected there,
            # so files go directly into the artist's chosen directory.
            macro="{outputs}/{sub_dirs?:/}{file_name_base}{####?:^_v}.{file_extension}",
            policy=SituationPolicy(
                on_collision=SituationFilePolicy.CREATE_NEW,
                create_dirs=True,
            ),
            fallback="save_file",
        )

        template.situations["save_file"] = SituationTemplate(
            name="save_file",
            description="Generic file save operation",
            macro=(
                f"{{{SCRIPT_DIR_ENV_VAR}}}/{GRIPTAPE_RUN_DIR_NAME}/{{file_name_base}}{{###?:^_}}.{{file_extension}}"
            ),
            policy=SituationPolicy(
                on_collision=SituationFilePolicy.CREATE_NEW,
                create_dirs=True,
            ),
            fallback=None,
        )

        template.situations["save_workflow"] = SituationTemplate(
            name="save_workflow",
            description="Save a workflow Python file, preserving any sub-directory hierarchy",
            macro=(
                f"{{{SCRIPT_DIR_ENV_VAR}}}/{GRIPTAPE_RUN_DIR_NAME}/{{sub_dirs?:/}}{{file_name_base}}.{{file_extension}}"
            ),
            policy=SituationPolicy(
                on_collision=SituationFilePolicy.OVERWRITE,
                create_dirs=True,
            ),
            fallback="save_file",
        )

        template.situations["create_versioned_workflow"] = SituationTemplate(
            name="create_versioned_workflow",
            description="Save a new version of a workflow with a padded index suffix",
            macro=(
                f"{{{SCRIPT_DIR_ENV_VAR}}}/{GRIPTAPE_RUN_DIR_NAME}/"
                "{sub_dirs?:/}{file_name_base}{###?:^_v}.{file_extension}"
            ),
            policy=SituationPolicy(
                on_collision=SituationFilePolicy.CREATE_NEW,
                create_dirs=True,
            ),
            fallback="save_file",
        )

        # A run's own inputs are written beside the .nk script even though the `inputs`
        # DIRECTORY stays inside the bundle: that directory holds the read-only assets the
        # packager shipped, which is not somewhere a run may add to.
        template.situations["copy_external_file"] = SituationTemplate(
            name="copy_external_file",
            description="User copies external file to project",
            macro=(
                f"{{{SCRIPT_DIR_ENV_VAR}}}/{GRIPTAPE_RUN_DIR_NAME}/inputs/{{file_extension_directory?:/}}"
                "{file_name_base}{###?:^_}.{file_extension}"
            ),
            policy=SituationPolicy(
                on_collision=SituationFilePolicy.CREATE_NEW,
                create_dirs=True,
            ),
            fallback="save_file",
        )

        template.situations["download_url"] = SituationTemplate(
            name="download_url",
            description="Download file from URL",
            macro=(
                f"{{{SCRIPT_DIR_ENV_VAR}}}/{GRIPTAPE_RUN_DIR_NAME}/inputs/"
                "{file_extension_directory?:/}{sanitized_url}"
            ),
            policy=SituationPolicy(
                on_collision=SituationFilePolicy.OVERWRITE,
                create_dirs=True,
            ),
            fallback="save_file",
        )
        # No script-dir prefix, because {static_files_dir} is not a directory macro, it
        # is the `static_files_directory` config value, which the runner sets to an
        # absolute path beside the .nk.
        template.situations["save_static_file"] = SituationTemplate(
            name="save_static_file",
            description=(
                "Save static file to workflow-relative staticfiles directory. "
                "Required for projects using StaticFilesManager.save_static_file."
            ),
            macro="{static_files_dir}/{file_name_base}.{file_extension}",
            policy=SituationPolicy(
                on_collision=SituationFilePolicy.OVERWRITE,
                create_dirs=True,
            ),
            fallback="save_file",
        )

        write_result = GriptapeNodes.handle_request(
            WriteFileRequest(file_path=str(project_yml), content=template.to_yaml(), encoding="utf-8")
        )
        if not isinstance(write_result, WriteFileResultSuccess):
            msg = f"Failed to write the customized project.yml to '{project_yml}'."
            logger.error(msg)
            raise TypeError(msg)

    # -- Validation and path helpers --

    def _validate(self) -> list[Exception]:
        errors: list[Exception] = []
        if self._get_nuke_start_flow_node() is None:
            errors.append(ValueError("No NukeStartFlow node found in the workflow."))
            return errors
        install_dir = self._resolve_gizmo_install_path()
        if install_dir is None:
            errors.append(ValueError("Gizmo install path is not configured. Please set it in the publish dialog."))
        elif install_dir.exists() and not install_dir.is_dir():
            # A directory that does not exist yet is fine -- the publish creates it, which
            # is how first-time config of a machine with no ~/.nuke works. Only something
            # already occupying the path is fatal, and it is caught here so the publish
            # stops before it writes a partial bundle. Reported with the resolved path so
            # a relative pick that got anchored to the workspace is visible.
            errors.append(
                ValueError(
                    f"Gizmo install path '{install_dir}' exists but is not a directory. "
                    "Please choose a directory in the publish dialog."
                )
            )
        return errors

    def _resolve_gizmo_install_path(self) -> Path | None:
        """Return the install directory as an absolute path, anchoring a relative one to the workspace.

        A relative path cannot survive this publish, because one value gets resolved
        against different bases depending on which layer touches it: the engine's event
        layer anchors relative paths to the workspace, while the plain ``pathlib`` calls
        here anchor them to the engine's working directory. Which requests do which has
        varied across engine releases, and a re-publish to a workspace-relative path
        fails even on an engine that anchors both reads and writes. Anchoring once, here,
        makes the publish independent of all of that.

        ``absolutize`` rather than the engine's ``resolve_workspace_path`` because the
        latter calls ``Path.resolve()`` on absolute paths too. A studio share is
        routinely reached through a symlink, and resolving it substitutes a
        host-specific target for the path the publisher actually chose.
        """
        choice = self._metadata.get("gizmo_install_path")
        if choice == GIZMO_INSTALL_CUSTOM:
            choice = self._metadata.get("custom_gizmo_path")
        if not choice:
            return None
        return Path(absolutize(str(choice), str(GriptapeNodes.ConfigManager().workspace_path)))

    def _get_nuke_start_flow_node(self):  # noqa: ANN202
        result = GriptapeNodes.handle_request(GetTopLevelFlowRequest())
        if not isinstance(result, GetTopLevelFlowResultSuccess) or result.flow_name is None:
            return None
        control_flow = GriptapeNodes.FlowManager().get_flow_by_name(result.flow_name)
        for node in control_flow.nodes.values():
            if node.__class__.__name__ == "NukeStartFlow":
                return node
        return None

    # -- Version management --

    def _get_saved_version(self) -> int | None:
        start_flow = self._get_nuke_start_flow_node()
        if start_flow is not None:
            v = start_flow.metadata.get("publish_config", {}).get("version")
            if v is not None:
                return int(v)
        v = self._metadata.get("version")
        return int(v) if v is not None else None

    def _collect_versions(self, companion_base: Path) -> list[int]:
        """Return a sorted list of version numbers from existing version subdirs."""
        if not companion_base.exists():
            return []
        versions = []
        for p in companion_base.iterdir():
            if p.is_dir() and p.name.startswith("v"):
                try:
                    versions.append(int(p.name[1:]))
                except ValueError:
                    continue
        return sorted(versions)

    def _determine_version(self, companion_base: Path) -> int:
        update_mode = self._metadata.get("update_mode", "").lower()
        saved_version = self._get_saved_version()

        if "new version" in update_mode:
            return (saved_version or 0) + 1
        if "current version" in update_mode and saved_version is not None:
            return saved_version

        existing = self._collect_versions(companion_base)
        return max(existing) + 1 if existing else 1

    def _save_publish_config(self, gizmo_path: Path, version: int) -> None:
        start_flow = self._get_nuke_start_flow_node()
        if start_flow is None:
            return
        # Store the resolved custom path so the next publish dialog round-trips an
        # absolute value instead of the relative one the file picker handed back.
        custom_path = self._metadata.get("custom_gizmo_path")
        if custom_path:
            custom_path = absolutize(str(custom_path), str(GriptapeNodes.ConfigManager().workspace_path))
        start_flow.metadata["publish_config"] = {
            "gizmo_install_path": self._metadata.get("gizmo_install_path"),
            "custom_gizmo_path": custom_path,
            "gizmo_path": str(gizmo_path),
            "version": version,
        }

    # -- Plugin registration file writers --

    def _ensure_init_plugin_path(self, install_dir: Path) -> None:
        """Append a single pluginAddPath for the griptape dir to init.py, once.

        Uses a marker comment to detect an existing entry so subsequent
        publishes are no-ops and the user's own init.py content is preserved.
        """
        init_path = install_dir / "init.py"
        read_result = GriptapeNodes.handle_request(
            ReadFileRequest(file_path=str(init_path), workspace_only=False, encoding="utf-8")
        )
        existing = (
            read_result.content
            if isinstance(read_result, ReadFileResultSuccess) and isinstance(read_result.content, str)
            else ""
        )
        if INIT_MARKER in existing:
            return

        line = (
            f"import nuke as _nuke, os as _os  {INIT_MARKER}\n"
            f"_nuke.pluginAddPath(_os.path.join(_os.path.dirname(__file__), '{GRIPTAPE_DIR_NAME}'))"
        )
        updated = (existing.rstrip("\n") + "\n\n" + line + "\n") if existing.strip() else line + "\n"
        write_result = GriptapeNodes.handle_request(
            WriteFileRequest(file_path=str(init_path), content=updated, encoding="utf-8")
        )
        if not isinstance(write_result, WriteFileResultSuccess):
            msg = f"Failed to write init.py at '{init_path}'."
            logger.error(msg)
            raise TypeError(msg)
        logger.info("init.py updated at: %s", init_path)

    def _regenerate_menu_py(self, griptape_dir: Path) -> None:
        """Write griptape/menu.py with a dynamic refresh function.

        The generated menu.py defines ``_refresh_griptape_menu()`` which uses
        ``nuke.plugins()`` to discover ALL versioned ``.gizmo`` files at call time,
        calls ``nuke.load()`` on each to force Nuke to re-read the TCL from disk,
        and rebuilds the Griptape node-creation entries on the Nodes toolbar.
        The refresh tracks the menu items it adds (module-level list in the
        generated code) and removes only those on each rescan, so the
        Nodes > Griptape menu can be shared with other plugins (e.g. Nuke's
        built-in Griptape workflow node).

        "Refresh Griptape Gizmos" lives on the main Nuke menu bar (not the Nodes
        toolbar) so that clicking it never triggers Nuke's node-placement mode.

        When a workflow has multiple published versions each version gets its own
        entry inside a per-workflow submenu (e.g. Griptape > My Workflow > v1 / v2).
        Single-version workflows get a flat entry with no submenu.
        """
        menu_code = """\
import nuke
import os

# Qt is bundled with Nuke. Try PySide6 first (Nuke 16+), fall back to PySide2 (Nuke 13-15).
try:
    from PySide6.QtCore import QFileSystemWatcher
    _QT_AVAILABLE = True
except ImportError:
    try:
        from PySide2.QtCore import QFileSystemWatcher
        _QT_AVAILABLE = True
    except ImportError:
        _QT_AVAILABLE = False

_GRIPTAPE_DIR = os.path.dirname(__file__)

# Module-level reference keeps the watcher alive (Python GC would drop a local).
_GRIPTAPE_WATCHER = None

# Labels of items THIS script added to Nodes > Griptape. The menu is shared --
# other plugins (e.g. Nuke's built-in Griptape workflow node) may add items --
# so a refresh must only remove entries we created, never the whole menu.
_GRIPTAPE_MENU_ITEMS = []


def _refresh_griptape_menu():
    \"\"\"Rescan the griptape directory and rebuild the Griptape node-creation menu.

    Call this after publishing a new or updated gizmo to make it available
    without restarting Nuke.

    Only entries added by this script are removed and re-added; items other
    plugins placed in the Griptape menu are left untouched.
    \"\"\"
    # Remove then re-add the path to force Nuke to re-walk the directory.
    # pluginAddPath is idempotent on an already-registered path; the remove
    # invalidates the cached walk so nuke.plugins() sees newly written files.
    # pluginRemovePath is undocumented — guard against versions that lack it.
    if hasattr(nuke, 'pluginRemovePath'):
        nuke.pluginRemovePath(_GRIPTAPE_DIR)
    nuke.pluginAddPath(_GRIPTAPE_DIR)

    # Use nuke.ALL so Nuke walks all plugin_path() directories (not just loaded plugins).
    gizmo_paths = nuke.plugins(nuke.ALL, '*_v*.gizmo')

    # Collect ALL versions per stem (not just the highest).
    # Filenames follow the pattern "<stem>_v<N>.gizmo"; we parse with rsplit.
    workflows = {}  # stem -> sorted list of (version, node_name)
    for path in gizmo_paths:
        fname = os.path.basename(path)
        if not fname.endswith('.gizmo'):
            continue
        name = fname[:-len('.gizmo')]  # e.g. "my_workflow_v02"
        parts = name.rsplit('_v', 1)
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        stem, ver = parts[0], int(parts[1])
        workflows.setdefault(stem, []).append((ver, name))

    for stem in workflows:
        workflows[stem].sort()

    # Get-or-create the Griptape submenu on the Nodes toolbar. addMenu()
    # returns the existing menu when one with this name already exists, so
    # items added by other plugins (e.g. Nuke's built-in Griptape workflow
    # node) are preserved. Never remove the menu itself.
    nodes_toolbar = nuke.menu('Nodes')
    griptape_nodes = nodes_toolbar.addMenu('Griptape')

    # Remove only the entries added by a previous refresh so repeated calls
    # don't accumulate duplicates and deleted gizmos disappear from the menu.
    global _GRIPTAPE_MENU_ITEMS
    for _item_name in _GRIPTAPE_MENU_ITEMS:
        try:
            griptape_nodes.removeItem(_item_name)
        except Exception:
            pass
    _GRIPTAPE_MENU_ITEMS = []

    # If all items were removed, then the menu itself is removed and we
    # have a dangling pointer, potentially leading to segfault, so
    # idempotently re-add the menu.
    griptape_nodes = nodes_toolbar.addMenu('Griptape')

    for stem in sorted(workflows):
        label = stem.replace('_', ' ').title()
        versions = workflows[stem]
        if len(versions) == 1:
            # Only one version — flat entry, no submenu.
            node_name = versions[0][1]
            griptape_nodes.addCommand(label, "nuke.createNode('{}')".format(node_name))
        else:
            # Multiple versions — nest them under a per-workflow submenu.
            workflow_submenu = griptape_nodes.addMenu(label)
            for ver, node_name in versions:
                workflow_submenu.addCommand('v{}'.format(ver), "nuke.createNode('{}')".format(node_name))
        _GRIPTAPE_MENU_ITEMS.append(label)


# "Refresh Griptape Gizmos" lives on the main Nuke menu bar so that clicking
# it never triggers node-placement mode on the Nodes toolbar.
nuke.menu('Nuke').addMenu('Griptape').addCommand('Refresh Griptape Gizmos', _refresh_griptape_menu)

# Populate the Nodes toolbar on startup.
_refresh_griptape_menu()

# Watch the griptape directory for new/removed gizmos and auto-refresh the menu.
# Skipped silently when Qt cannot be imported.
if _QT_AVAILABLE:
    _GRIPTAPE_WATCHER = QFileSystemWatcher([_GRIPTAPE_DIR])
    _GRIPTAPE_WATCHER.directoryChanged.connect(lambda _path: _refresh_griptape_menu())

    def _griptape_is_remote_mount(path):
        \"\"\"Return True when path is likely on a network/remote filesystem.\"\"\"
        import sys
        try:
            if sys.platform == 'darwin':
                # /Volumes/<name> on a different device than / means a separate mount.
                if os.path.normpath(path).startswith('/Volumes/'):
                    return os.stat(path).st_dev != os.stat('/').st_dev
            elif sys.platform == 'win32':
                # UNC paths (\\\\server\\share\\...) are network by definition.
                return os.path.normpath(path).startswith('\\\\\\\\')
            else:
                # Linux/other: check /proc/self/mountinfo for the fs type.
                _REMOTE_FS = {'nfs', 'nfs4', 'cifs', 'smb', 'smbfs', 'fuse.sshfs'}
                norm = os.path.normpath(path)
                best_mp = ''
                best_fs = ''
                with open('/proc/self/mountinfo', encoding='utf-8') as _f:
                    for _line in _f:
                        _parts = _line.split()
                        # Field 4 is the mount point; field after ' - ' is fs type.
                        _mp = _parts[4]
                        try:
                            _dash = _parts.index('-')
                            _fs = _parts[_dash + 1]
                        except (ValueError, IndexError):
                            continue
                        if (norm == _mp or norm.startswith(_mp.rstrip('/') + '/')) and len(_mp) > len(best_mp):
                            best_mp = _mp
                            best_fs = _fs
                return best_fs.lower() in _REMOTE_FS
        except Exception:
            return False

    if _griptape_is_remote_mount(_GRIPTAPE_DIR):
        _msg = (
            '[Griptape] Install dir appears to be on a network mount: ' + _GRIPTAPE_DIR + '\\n'
            '[Griptape] QFileSystemWatcher may not deliver change events on remote filesystems.\\n'
            '[Griptape] Use Nuke menu > Griptape > Refresh Griptape Gizmos after publishing.'
        )
        try:
            nuke.tprint(_msg)
        except Exception:
            print(_msg)
"""
        menu_py_path = griptape_dir / "menu.py"
        write_result = GriptapeNodes.handle_request(
            WriteFileRequest(file_path=str(menu_py_path), content=menu_code, encoding="utf-8")
        )
        if not isinstance(write_result, WriteFileResultSuccess):
            msg = f"Failed to write menu.py at '{menu_py_path}'."
            logger.error(msg)
            raise TypeError(msg)
        logger.info("menu.py regenerated at: %s", menu_py_path)
