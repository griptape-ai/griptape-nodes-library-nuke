"""Negotiate a protocol version, claim this engine's exclusive lease, and open the event stream."""

from __future__ import annotations

from nuke_host_api import execution_bridge, library_version, session
from nuke_host_api.dispatch import failure, verb
from nuke_host_api.engine import emit_event, engine_version, event_topic
from nuke_host_api.events import (
    NukeConnectRequest,
    NukeConnectResultFailure,
    NukeConnectResultSuccess,
    NukeSessionRevokedEvent,
)
from nuke_host_api.protocol import PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS, VALUE_TYPES


@verb(NukeConnectRequest)
def handle_connect(request: NukeConnectRequest) -> NukeConnectResultSuccess | NukeConnectResultFailure:
    """Agree a protocol version, settle who owns the engine, and hand over the event topic.

    Nuke drives an engine as if it owns it, so exactly one client may hold it at a time; see
    ``session.py``. A version mismatch is refused before the lease is even considered, since
    without an agreed vocabulary nothing else here would mean anything to the caller. Also
    installs the outbound event bridge, so a host must connect before it can receive
    notifications. Connecting is the handshake, so gating the stream on it costs a host
    nothing it was not already doing, and it keeps an engine that no host talks to free of
    the bridge's engine-global subscription.
    """
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

    claimed = session.claim(request.client_id, client, force=request.force)
    if not claimed.granted:
        return failure(
            NukeConnectResultFailure,
            attempted=f"to connect {client} to this engine",
            because=claimed.refusal_reason,
            error=PermissionError,
            supported_protocol_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
            holder_client_name=claimed.holder_client_name,
            holder_idle_seconds=claimed.holder_idle_seconds,
        )

    if claimed.revoked_client_id:
        emit_event(
            NukeSessionRevokedEvent(
                revoked_client_id=claimed.revoked_client_id,
                new_holder_client_name=client,
                reason=claimed.revocation_reason,
            )
        )

    # Notifications start here, not at library load. The bridge's subscription is
    # engine-global, so an engine no host has connected to should not pay to translate and
    # re-emit every execution event it runs.
    execution_bridge.ensure_installed()

    return NukeConnectResultSuccess(
        protocol_version=mutual[0],
        supported_protocol_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
        engine_version=engine_version(),
        library_version=library_version.version(),
        event_topic=event_topic(),
        value_types=list(VALUE_TYPES),
        session_token=claimed.session_token,
        result_details=f"Connected {client} on host API protocol version {mutual[0]}.",
    )
