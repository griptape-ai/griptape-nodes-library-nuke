"""The host drives its workflow while an editor tab holds another open in the same engine.

No Nuke and no engine process: a real engine in-process, driven through the host handlers. The
engine refuses a request that names no workflow once two are open, which is the failure in
griptape-ai/griptape-nodes-library-nuke#204.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any

import pytest
from griptape_nodes.retained_mode.events.context_events import OpenWorkflowRequest, OpenWorkflowResultSuccess
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api import execution_bridge, notify
from nuke_host_api.events import (
    NukeExecuteWorkflowRequest,
    NukeExecuteWorkflowResultSuccess,
    NukeExecutionStateEvent,
    NukeGetParameterValuesRequest,
    NukeGetParameterValuesResultSuccess,
    NukeLoadWorkflowRequest,
    NukeLoadWorkflowResultSuccess,
)
from nuke_host_api.handlers import handle_execute_workflow, handle_get_parameter_values, handle_load_workflow
from nuke_host_api.protocol import ExecutionState
from tests.detached_run import settled

from .fixtures.canary.canary_workflow_builder import build_start_canary_end_flow

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

WORKFLOW = "multi_canary"


def _open_ids() -> set[str]:
    return {workflow.workflow_id for workflow in GriptapeNodes.get_instance().open_workflows.all_open()}


@pytest.fixture
def verdicts(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[NukeExecutionStateEvent]]:
    published: list[NukeExecutionStateEvent] = []

    def capture(payload: Any) -> None:
        if isinstance(payload, NukeExecutionStateEvent):
            published.append(payload)

    monkeypatch.setattr(notify, "publish", capture)
    execution_bridge.ensure_installed()
    yield published
    execution_bridge.uninstall()


@pytest.fixture
async def editor_tab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Save the canary workflow, then open a second workflow as an editor tab would."""
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name=WORKFLOW)
    opened = await GriptapeNodes.ahandle_request(OpenWorkflowRequest(display_name="Editor tab", create_flow=True))
    assert isinstance(opened, OpenWorkflowResultSuccess), opened.result_details
    assert len(_open_ids()) == 2, "the premise is two open workflows"
    return opened.open_workflow.workflow_id


async def _load(*, workflow_id: str = WORKFLOW, file_path: str = "") -> NukeLoadWorkflowResultSuccess:
    if file_path:
        workflow_id = ""
    result = await handle_load_workflow(NukeLoadWorkflowRequest(workflow_id=workflow_id, file_path=file_path))
    assert isinstance(result, NukeLoadWorkflowResultSuccess), result.result_details
    return result


async def test_the_host_loads_reads_and_runs_its_workflow(
    editor_tab: str, verdicts: list[NukeExecutionStateEvent]
) -> None:
    await _load()

    values = await handle_get_parameter_values(NukeGetParameterValuesRequest())
    assert isinstance(values, NukeGetParameterValuesResultSuccess), values.result_details
    assert values.workflow_id == WORKFLOW

    started = await handle_execute_workflow(NukeExecuteWorkflowRequest(workflow_id=WORKFLOW))
    assert isinstance(started, NukeExecuteWorkflowResultSuccess), started.result_details
    await settled()

    assert [v.state for v in verdicts] == [ExecutionState.SUCCEEDED], verdicts
    assert editor_tab in _open_ids(), "the editor's workflow must stay open"


async def test_load_takes_a_workflow_already_open_as_it_is(editor_tab: str) -> None:
    """The builder leaves the saved workflow open, as an editor tab would, so loading it opens nothing."""
    before = _open_ids()

    await _load()

    assert _open_ids() == before
    assert editor_tab in _open_ids()


async def test_loading_another_workflow_closes_the_one_the_host_opened(editor_tab: str, tmp_path: Path) -> None:
    """A workflow the host found open, such as the saved canary here, stays open."""
    other = tmp_path / "other_canary.py"
    shutil.copy(tmp_path / "workspace" / f"{WORKFLOW}.py", other)
    before = _open_ids()
    await _load(file_path=str(other))
    assert len(_open_ids()) == len(before) + 1, "the host opened the copy"

    await _load()

    assert _open_ids() == before
    assert editor_tab in _open_ids()
