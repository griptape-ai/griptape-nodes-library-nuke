"""Guards constants that are intentionally duplicated across modules against drift.

Each guarded module keeps its own copy of the literal rather than importing it from
the other -- see each module's comment at the definition site for why -- and this
file is the single source of truth that keeps the copies honest. Each class below
covers one such duplicated-literal pair.
"""

from __future__ import annotations

import nuke_workflow_runner

from publish_gizmo import constants, nuke_gizmo_publisher, output_paths, tcl_utils


class TestGtExprPrefixSync:
    """Guards the GT_EXPR_PREFIX literal against drift between constants.py and tcl_utils.py."""

    def test_gt_expr_prefix_matches_between_constants_and_tcl_utils(self) -> None:
        assert tcl_utils.GT_EXPR_PREFIX == constants.GT_EXPR_PREFIX


class TestOutputsDirEnvVarSync:
    """Guards OUTPUTS_DIR_ENV_VAR against drift between nuke_workflow_runner.py and nuke_gizmo_publisher.py."""

    def test_outputs_dir_env_var_matches_between_runner_and_publisher(self) -> None:
        assert nuke_workflow_runner.OUTPUTS_DIR_ENV_VAR == nuke_gizmo_publisher.OUTPUTS_DIR_ENV_VAR


class TestScriptDirEnvVarSync:
    """Guards SCRIPT_DIR_ENV_VAR against drift between nuke_workflow_runner.py and nuke_gizmo_publisher.py."""

    def test_script_dir_env_var_matches_between_runner_and_publisher(self) -> None:
        assert nuke_workflow_runner.SCRIPT_DIR_ENV_VAR == nuke_gizmo_publisher.SCRIPT_DIR_ENV_VAR


class TestGriptapeRunDirNameSync:
    """Guards GRIPTAPE_RUN_DIR_NAME against drift between nuke_workflow_runner.py and constants.py.

    The runner executes standalone inside the published bundle, where publish_gizmo is not
    importable, so it keeps its own copy of the hidden run directory's name.
    """

    def test_griptape_run_dir_name_matches_between_runner_and_constants(self) -> None:
        assert nuke_workflow_runner.GRIPTAPE_RUN_DIR_NAME == constants.GRIPTAPE_RUN_DIR_NAME


class TestOutputsDirNameSync:
    """Guards OUTPUTS_DIR_NAME against drift between output_paths.py and constants.py.

    output_paths.py cannot import constants.py at bundle runtime (it isn't copied into the
    companion bundle -- see NukeGizmoPublisher.publish_workflow), so it keeps its own copy.
    """

    def test_outputs_dir_name_matches_between_output_paths_and_constants(self) -> None:
        assert output_paths.OUTPUTS_DIR_NAME == constants.OUTPUTS_DIR_NAME
