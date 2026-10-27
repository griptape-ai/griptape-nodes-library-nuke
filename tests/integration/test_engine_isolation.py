"""The autouse isolation keeps an in-process engine's scaffolding inside the test's tmp_path."""

from __future__ import annotations

from typing import TYPE_CHECKING

from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

if TYPE_CHECKING:
    from pathlib import Path


def test_an_engine_booted_before_any_test_workspace_scaffolds_inside_tmp_path(tmp_path: Path) -> None:
    GriptapeNodes.ConfigManager()

    assert (tmp_path / "workspace" / "synced_workflows").is_dir()
