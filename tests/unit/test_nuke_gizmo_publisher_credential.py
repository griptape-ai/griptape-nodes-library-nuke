"""Tests for NukeGizmoPublisher._backfill_cloud_credential.

The desktop injects the Griptape Cloud credential into the engine process env
without writing it to any .env, so the packager misses it. The publisher must
backfill it into the bundle .env from SecretsManager (which reads process env).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from griptape_nodes.retained_mode.events.os_events import ReadFileResultSuccess, WriteFileResultSuccess

from publish_gizmo.nuke_gizmo_publisher import NukeGizmoPublisher

_MODULE = "publish_gizmo.nuke_gizmo_publisher.GriptapeNodes"


def _run_backfill(existing_env: str, secrets: dict[str, str | None]) -> str | None:
    """Invoke _backfill_cloud_credential with a mocked bundle .env and SecretsManager.

    Returns the content written to the bundle .env, or None if no write happened.
    """
    written: dict[str, str] = {}

    def _handle_request(request):
        req_type = type(request).__name__
        if req_type == "ReadFileRequest":
            result = MagicMock(spec=ReadFileResultSuccess)
            result.content = existing_env
            return result
        if req_type == "WriteFileRequest":
            written["content"] = request.content
            return MagicMock(spec=WriteFileResultSuccess)
        msg = f"unexpected request {req_type}"
        raise AssertionError(msg)

    secrets_manager = MagicMock()
    secrets_manager.get_secret.side_effect = lambda name, **_: secrets.get(name)

    with patch(_MODULE) as gtn:
        gtn.handle_request.side_effect = _handle_request
        gtn.SecretsManager.return_value = secrets_manager
        NukeGizmoPublisher._backfill_cloud_credential(Path("/tmp/companion"))

    return written.get("content")


class TestBackfillCloudCredential:
    def test_backfills_api_key_when_missing(self) -> None:
        content = _run_backfill(existing_env="OTHER=1\n", secrets={"GT_CLOUD_API_KEY": "minted-key"})
        assert content is not None
        assert 'GT_CLOUD_API_KEY="minted-key"' in content
        assert "OTHER=1" in content

    def test_backfills_license_when_missing(self) -> None:
        content = _run_backfill(
            existing_env="",
            secrets={"GRIPTAPE_NODES_LICENSE": "the-license", "GT_CLOUD_API_KEY": None},
        )
        assert content is not None
        assert 'GRIPTAPE_NODES_LICENSE="the-license"' in content

    def test_does_not_overwrite_existing_key(self) -> None:
        content = _run_backfill(
            existing_env='GT_CLOUD_API_KEY="on-disk-key"\n',
            secrets={"GT_CLOUD_API_KEY": "process-env-key"},
        )
        # No write should occur because the key already exists in the bundle .env.
        assert content is None

    def test_no_credential_anywhere_writes_nothing(self) -> None:
        content = _run_backfill(existing_env="OTHER=1\n", secrets={})
        assert content is None

    def test_backfills_both_when_both_present_and_missing(self) -> None:
        content = _run_backfill(
            existing_env="",
            secrets={"GRIPTAPE_NODES_LICENSE": "the-license", "GT_CLOUD_API_KEY": "minted-key"},
        )
        assert content is not None
        assert 'GRIPTAPE_NODES_LICENSE="the-license"' in content
        assert 'GT_CLOUD_API_KEY="minted-key"' in content
