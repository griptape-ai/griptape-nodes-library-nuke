"""The workflow list names the library that ships each library workflow.

No Nuke and no engine process: a real engine in-process, driven through the host handler.
"""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

from griptape_nodes.retained_mode.events.library_events import RegisterLibraryFromFileRequest
from griptape_nodes.retained_mode.events.workflow_events import RefreshWorkflowRegistryRequest, SaveWorkflowRequest
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from nuke_host_api.events import NukeListWorkflowsRequest, NukeListWorkflowsResultSuccess
from nuke_host_api.handlers import handle_list_workflows

from .fixtures.canary.canary_workflow_builder import build_start_canary_end_flow, materialize_canary_library

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

SHIPPING_LIBRARY = "Shipping Library"


async def test_a_workflow_a_library_lists_reports_that_librarys_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_start_canary_end_flow(tmp_path, monkeypatch, file_name="shipped")

    library_json = materialize_canary_library(tmp_path / "shipping_library")
    schema = json.loads(library_json.read_text())
    schema["name"] = SHIPPING_LIBRARY
    schema["workflows"] = ["workflows/shipped.py"]
    library_json.write_text(json.dumps(schema, indent=2))
    (library_json.parent / "workflows").mkdir()
    shipped = library_json.parent / "workflows" / "shipped.py"
    shutil.move(tmp_path / "workspace" / "shipped.py", shipped)
    # A library's own workflows say so in their header; a saved workflow says the opposite.
    header = shipped.read_text()
    assert "# is_griptape_provided = false\n" in header
    shipped.write_text(header.replace("# is_griptape_provided = false\n", "# is_griptape_provided = true\n", 1))

    result = GriptapeNodes.handle_request(SaveWorkflowRequest(file_name="users_workflow"))
    assert result.succeeded(), result
    result = GriptapeNodes.handle_request(RegisterLibraryFromFileRequest(file_path=str(library_json)))
    assert result.succeeded(), result
    result = await GriptapeNodes.ahandle_request(RefreshWorkflowRegistryRequest())
    assert result.succeeded(), result

    listed = await handle_list_workflows(NukeListWorkflowsRequest(runnable_only=False))

    assert isinstance(listed, NukeListWorkflowsResultSuccess), listed.result_details
    by_name = {w["name"]: w for w in listed.workflows}
    assert (by_name["shipped"]["library_provided"], by_name["shipped"]["library_name"]) == (True, SHIPPING_LIBRARY)
    assert (by_name["users_workflow"]["library_provided"], by_name["users_workflow"]["library_name"]) == (False, "")
