from __future__ import annotations

import logging
import time

from nuke_host_api import execution_bridge, host_claim, library_version, notify
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.engine import engine_id, engine_name, engine_version, event_topic, session_id
from nuke_host_api.events import (
    NukeConnectRequest,
    NukeConnectResultFailure,
    NukeConnectResultSuccess,
    NukeHostDisconnectEvent,
)
from nuke_host_api.protocol import (
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    VALUE_TYPES,
    DisconnectCause,
)

logger = logging.getLogger("griptape_nodes")


def _local_time(epoch_seconds: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch_seconds))


@verb(NukeConnectRequest)
async def handle_connect(request: NukeConnectRequest) -> NukeConnectResultSuccess | NukeConnectResultFailure:
    """Negotiate a version, claim the engine for one host, then install the event bridge."""
    offered = request.client_protocol_versions or [PROTOCOL_VERSION]
    mutual = sorted(set(offered) & set(SUPPORTED_PROTOCOL_VERSIONS), reverse=True)

    if not mutual:
        return failure(
            NukeConnectResultFailure,
            attempted=f"to connect a host speaking protocol version(s) {offered}",
            because=(
                f"this library supports {list(SUPPORTED_PROTOCOL_VERSIONS)}. "
                f"Update the host plugin, or install a library version that still supports it."
            ),
            error=ValueError,
            supported_protocol_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
        )

    client = host_claim.canonical_name(request.client_name)
    attempt = host_claim.claim(client, force=request.force)

    if not attempt.granted:
        return failure(
            NukeConnectResultFailure,
            attempted=f"to connect {client}",
            because=(
                f"{attempt.holder.client_name} connected to this engine at "
                f"{_local_time(attempt.holder.connected_at)} and is the host it reports. "
                f"Send force=true to become that host instead. The other host is not disconnected, "
                f"keeps its own event subscription, and can still drive this engine."
            ),
            supported_protocol_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
            host_client_name=attempt.holder.client_name,
            host_connected_at=attempt.holder.connected_at,
        )

    if attempt.displaced:
        logger.warning("Nuke host API: %s took the host claim from %s", client, attempt.displaced)
        # The transport cannot close another host's socket, so the displaced host is asked to.
        notify.publish(
            NukeHostDisconnectEvent(
                client_name=attempt.displaced,
                cause=DisconnectCause.CLAIM_TAKEN,
                reason=(
                    f"{client} connected with force and is the host this engine now reports. "
                    f"Disconnect, and connect again with force to take it back."
                ),
                replaced_by=client,
            )
        )

    # The bridge is engine-global, so defer its cost until a host needs notifications.
    execution_bridge.ensure_installed()

    return NukeConnectResultSuccess(
        protocol_version=mutual[0],
        supported_protocol_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
        engine_version=await engine_version(),
        library_version=library_version.version(),
        event_topic=event_topic(),
        value_types=list(VALUE_TYPES),
        engine_id=engine_id(),
        session_id=session_id(),
        engine_name=await engine_name(),
        host_client_name=attempt.holder.client_name,
        host_connected_at=attempt.holder.connected_at,
        displaced_client_name=attempt.displaced,
        result_details=f"Connected {client} on host API protocol version {mutual[0]}.",
    )
