from __future__ import annotations

from nuke_host_api import execution_bridge, library_version
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.engine import engine_id, engine_name, engine_version, event_topic, session_id
from nuke_host_api.events import (
    NukeConnectRequest,
    NukeConnectResultFailure,
    NukeConnectResultSuccess,
)
from nuke_host_api.protocol import PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS, VALUE_TYPES


@verb(NukeConnectRequest)
def handle_connect(request: NukeConnectRequest) -> NukeConnectResultSuccess | NukeConnectResultFailure:
    """Install the engine-global event bridge only after a host connects."""
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

    client = request.client_name or "unnamed host"

    # The bridge is engine-global, so defer its cost until a host needs notifications.
    execution_bridge.ensure_installed()

    return NukeConnectResultSuccess(
        protocol_version=mutual[0],
        supported_protocol_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
        engine_version=engine_version(),
        library_version=library_version.version(),
        event_topic=event_topic(),
        value_types=list(VALUE_TYPES),
        engine_id=engine_id(),
        session_id=session_id(),
        engine_name=engine_name(),
        result_details=f"Connected {client} on host API protocol version {mutual[0]}.",
    )
