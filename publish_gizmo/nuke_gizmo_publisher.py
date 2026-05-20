from __future__ import annotations

import logging
import shutil
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
    GRIPTAPE_DIR_NAME,
    INIT_MARKER,
    versioned_gizmo_filename,
)
from publish_gizmo.nuke_discovery import GIZMO_INSTALL_CUSTOM
from publish_gizmo.nuke_gizmo_builder import NukeGizmoBuilder

if TYPE_CHECKING:
    from griptape_nodes.retained_mode.events.base_events import ResultPayload

logger = logging.getLogger(__name__)


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
            logger.info("Workflow shape: %s", workflow_shape)

            self._packager.emit_progress(5.0, "Saving workflow...")
            workflow = WorkflowRegistry.get_workflow_by_name(self._workflow_name)
            save_result = GriptapeNodes.handle_request(SaveWorkflowRequest(file_name=Path(workflow.file_path).stem))
            if not isinstance(save_result, SaveWorkflowResultSuccess):
                return PublishWorkflowResultFailure(result_details="Failed to save workflow before packaging.")

            self._packager.emit_progress(5.0, "Packaging workflow bundle...")
            install_dir = self._resolve_gizmo_install_path()
            if install_dir is None:
                msg = "Gizmo install path is not set."
                raise ValueError(msg)

            workflow_file_path = Path(WorkflowRegistry.get_complete_file_path(workflow.file_path))
            workflow_stem = workflow_file_path.stem

            # All griptape artifacts live under a single subdirectory of the install dir
            griptape_dir = install_dir / GRIPTAPE_DIR_NAME
            companion_base = griptape_dir / workflow_stem

            version = self._determine_version(companion_base)
            version_dir = companion_base / f"v{version}"
            version_dir.mkdir(parents=True, exist_ok=True)

            # Package shared files (libraries, config, .env, pyproject.toml) into companion base.
            self._packager.package_to_folder(companion_base, workflow)

            # Override the bundled project.yml with Nuke-specific output conventions
            # so outputs land next to the .nk file, not inside the companion bundle.
            self._customize_project_yml(companion_base)

            # Move the workflow file from companion base into the version subdir
            src_workflow = companion_base / workflow_file_path.name
            dest_workflow = version_dir / workflow_file_path.name
            if src_workflow.exists():
                shutil.move(str(src_workflow), str(dest_workflow))

            # Copy the runner and button scripts (shared, overwrite on each publish)
            self._packager.emit_progress(5.0, "Writing runner script...")
            shutil.copy2(Path(__file__).parent / "nuke_workflow_runner.py", companion_base / "run_workflow.py")
            shutil.copy2(Path(__file__).parent / "run_button.py", companion_base / "run_button.py")

            available_versions = self._collect_versions(companion_base)

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
            return PublishWorkflowResultSuccess(
                published_workflow_file_path=str(gizmo_path),
                skip_published_workflow_registration=True,
                result_details=f"Gizmo v{version} installed to: {gizmo_path}",
            )
        except Exception as e:
            logger.exception("Failed to publish workflow '%s'", self._workflow_name)
            return PublishWorkflowResultFailure(result_details=f"Failed to publish workflow: {e}")

    # -- Project template customisation --

    @staticmethod
    def _customize_project_yml(companion_base: Path) -> None:
        """Override the bundled project.yml with Nuke-specific output conventions.

        * ``outputs`` directory is set to ``griptape_outputs`` (relative) so that
          outputs resolve next to the ``.nk`` file when a Nuke script directory
          is passed as the workspace at runtime.
        * ``save_node_output`` uses a naming convention compatible with Nuke conventions.
          The workflow name is hardcoded as a literal subdirectory (companion_base.name)
          rather than using the ``{workflow_name}`` builtin variable, which resolves to
          the workflow's full absolute path when the gizmo's companion directory is outside
          the user's workspace (i.e. always, since outputs go next to the .nk file).
          ``node_name`` is optional so that utility callers that omit it
          (e.g. pillow_nodes_library, video_utils, audio_utils) do not cause errors:
          ``{outputs}/<workflow_name>/{node_name?:_}{file_name_base}_v{_index?:04}.{file_extension}``
        """
        project_yml = companion_base / "project.yml"
        read_result = GriptapeNodes.handle_request(
            ReadFileRequest(file_path=str(project_yml), workspace_only=False, encoding="utf-8")
        )
        if not isinstance(read_result, ReadFileResultSuccess):
            return
        if not isinstance(read_result.content, str):
            return

        validation_info = ProjectValidationInfo(status=ProjectValidationStatus.GOOD)
        template = load_project_template_from_yaml(read_result.content, validation_info)
        if template is None:
            return

        template.directories["outputs"] = DirectoryDefinition(
            name="outputs",
            path_macro="griptape_outputs",
        )

        workflow_name = companion_base.name
        template.situations["save_node_output"] = SituationTemplate(
            name="save_node_output",
            description="Node generates and saves output (Nuke gizmo)",
            macro=f"{{outputs}}/{workflow_name}/{{node_name?:_}}{{file_name_base}}_v{{_index?:04}}.{{file_extension}}",
            policy=SituationPolicy(
                on_collision=SituationFilePolicy.CREATE_NEW,
                create_dirs=True,
            ),
            fallback="save_file",
        )

        write_result = GriptapeNodes.handle_request(
            WriteFileRequest(file_path=str(project_yml), content=template.to_yaml(), encoding="utf-8")
        )
        if not isinstance(write_result, WriteFileResultSuccess):
            logger.warning("Could not write customized project.yml to '%s'.", project_yml)

    # -- Validation and path helpers --

    def _validate(self) -> list[Exception]:
        errors: list[Exception] = []
        if self._get_nuke_start_flow_node() is None:
            errors.append(ValueError("No NukeStartFlow node found in the workflow."))
            return errors
        if self._resolve_gizmo_install_path() is None:
            errors.append(ValueError("Gizmo install path is not configured. Please set it in the publish dialog."))
        return errors

    def _resolve_gizmo_install_path(self) -> Path | None:
        choice = self._metadata.get("gizmo_install_path")
        if choice == GIZMO_INSTALL_CUSTOM:
            choice = self._metadata.get("custom_gizmo_path")
        if not choice:
            return None
        return Path(choice)

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
        start_flow.metadata["publish_config"] = {
            "nuke": self._metadata.get("nuke"),
            "gizmo_install_path": self._metadata.get("gizmo_install_path"),
            "custom_gizmo_path": self._metadata.get("custom_gizmo_path"),
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


def _refresh_griptape_menu():
    \"\"\"Rescan the griptape directory and rebuild the Griptape node-creation menu.

    Call this after publishing a new or updated gizmo to make it available
    without restarting Nuke.
    \"\"\"
    # Remove then re-add the path to force Nuke to re-walk the directory.
    # pluginAddPath is idempotent on an already-registered path, so without
    # the remove Nuke skips the walk and nuke.plugins() misses newly written files.
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

    # Rebuild the Griptape submenu on the Nodes toolbar.
    # Remove the existing entry first so repeated calls don't accumulate duplicates.
    nodes_toolbar = nuke.menu('Nodes')
    try:
        nodes_toolbar.removeItem('Griptape')
    except Exception:
        pass
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


# "Refresh Griptape Gizmos" lives on the main Nuke menu bar so that clicking
# it never triggers node-placement mode on the Nodes toolbar.
nuke.menu('Nuke').addMenu('Griptape').addCommand('Refresh Griptape Gizmos', _refresh_griptape_menu)

# Populate the Nodes toolbar on startup.
_refresh_griptape_menu()

# Watch the griptape directory for new/removed gizmos and auto-refresh the menu.
# Skipped silently when Qt is unavailable (e.g. nuke -t headless).
if _QT_AVAILABLE:
    _GRIPTAPE_WATCHER = QFileSystemWatcher([_GRIPTAPE_DIR])
    _GRIPTAPE_WATCHER.directoryChanged.connect(lambda _path: _refresh_griptape_menu())
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
