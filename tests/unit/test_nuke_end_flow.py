"""Unit tests for NukeEndFlow's output-value dict override."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from griptape.artifacts import BlobArtifact, ImageArtifact, ImageUrlArtifact
from griptape_nodes.exe_types.node_types import TrackedParameterOutputValues

from nuke_nodes.nuke_end_flow import NukeEndFlow, _NukeEndFlowTrackedParameterOutputValues


@pytest.fixture
def node() -> Mock:
    return Mock(spec=NukeEndFlow)


class TestNukeEndFlowTrackedParameterOutputValuesSetItem:
    @pytest.fixture
    def mock_base_setitem(self, monkeypatch) -> Mock:
        """Stand-in for the owning node; no parameter is registered, so no event is emitted."""
        mock_setitem = Mock()
        monkeypatch.setattr(TrackedParameterOutputValues, "__setitem__", mock_setitem)
        return mock_setitem

    def test_url_artifact_is_stored_as_its_plain_string(self, node: Mock, mock_base_setitem: Mock) -> None:
        values = _NukeEndFlowTrackedParameterOutputValues(node)

        values["value"] = ImageUrlArtifact(value="x.png")

        mock_base_setitem.assert_called_once_with("value", "x.png")

    def test_non_url_artifact_is_stored_unchanged(self, node: Mock, mock_base_setitem: Mock) -> None:
        values = _NukeEndFlowTrackedParameterOutputValues(node)
        artifact = ImageArtifact(value=b"\x89PNG\r\n", format="png", width=1, height=1)

        values["value"] = artifact

        mock_base_setitem.assert_called_once_with("value", artifact)

    def test_binary_blob_artifact_is_stored_unchanged_without_decoding(
        self, node: Mock, mock_base_setitem: Mock
    ) -> None:
        values = _NukeEndFlowTrackedParameterOutputValues(node)
        artifact = BlobArtifact(value=b"\xff\xfe\x00\x01binary")

        values["value"] = artifact

        mock_base_setitem.assert_called_once_with("value", artifact)

    def test_plain_string_is_stored_unchanged(self, node: Mock, mock_base_setitem: Mock) -> None:
        values = _NukeEndFlowTrackedParameterOutputValues(node)

        values["value"] = "x.png"

        mock_base_setitem.assert_called_once_with("value", "x.png")

    def test_none_is_stored_unchanged(self, node: Mock, mock_base_setitem: Mock) -> None:
        values = _NukeEndFlowTrackedParameterOutputValues(node)

        values["value"] = None

        mock_base_setitem.assert_called_once_with("value", None)
