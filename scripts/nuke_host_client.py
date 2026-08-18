#!/usr/bin/env python3
"""Reference host client for the Nuke host API.

Stands in for the Nuke C++ plugin and doubles as the conformance check. Everything it
does, the plugin must be able to do: connect, discover, execute, and listen. It imports
nothing from the engine, by design.

Exercises the four capabilities:
  1. connect            NukeConnectRequest, including protocol negotiation
  2. execute workflows  NukeExecuteWorkflowRequest / NukeGetExecutionStateRequest / NukeCancelExecutionRequest
  3. node execution     NukeNodeStateEvent on the event topic
  4. parameter values   NukeParameterValueEvent, values already normalized

Prerequisites: this library installed in the engine, and the engine running with the
`websocket_direct` IPC driver enabled. Check the driver with
`GetConfigValueRequest(category_and_key="ipc_drivers")` and set WS_URL to match.

    uv run python scripts/nuke_host_client.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect

WS_URL = "ws://127.0.0.1:18125"
REPLY_TOPIC = "nuke-host/reply"
REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_JSON = REPO_ROOT / "griptape-nodes-library.json"
TIMEOUT_S = 60.0
RUN_TIMEOUT_S = 20.0


class NukeClient:
    """Request/reply plus notification stream over the engine's direct WebSocket driver."""

    def __init__(self, ws) -> None:  # noqa: ANN001
        self._ws = ws
        self._notifications: list[dict[str, Any]] = []

    @property
    def notifications(self) -> list[dict[str, Any]]:
        """Host notifications seen so far, in arrival order."""
        return self._notifications

    async def subscribe(self, topic: str) -> None:
        await self._ws.send(json.dumps({"type": "subscribe", "topic": topic}))

    async def request(self, request_type: str, payload: dict | None = None) -> dict:
        """Send one request and wait for the reply with a matching request_id."""
        request_id = uuid.uuid4().hex
        await self._ws.send(
            json.dumps(
                {
                    "payload": {
                        "event_type": "EventRequest",
                        "request_type": request_type,
                        "request": payload or {},
                        "request_id": request_id,
                        "response_topic": REPLY_TOPIC,
                    }
                }
            )
        )
        return await self._pump(until_request_id=request_id)

    async def drain(self, seconds: float) -> None:
        """Collect notifications for a while, ignoring replies."""
        try:
            await asyncio.wait_for(self._pump(until_request_id=None), timeout=seconds)
        except TimeoutError:
            pass

    async def _pump(self, until_request_id: str | None) -> dict:
        """Read frames, recording notifications, until the awaited reply arrives.

        Notifications and replies share the socket, so a client that only waits for
        replies drops events. The plugin needs this same loop.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + TIMEOUT_S
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                msg = f"Timed out waiting for a reply to {until_request_id}"
                raise TimeoutError(msg)
            raw = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
            # A frame that will not parse into an object is not worth killing the pump for. The
            # awaited reply may still be behind it.
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(frame, dict):
                continue
            payload = frame.get("payload", {})

            if frame.get("type") == "app_event" or payload.get("event_type") == "AppEvent":
                payload_type = payload.get("payload_type", "")
                # Only this protocol's notifications. Other libraries broadcast app events
                # too, and a stale copy of this library would broadcast an older vocabulary.
                if payload_type.startswith("Nuke"):
                    self._notifications.append({"type": payload_type, "body": payload.get("payload", {})})
                continue

            if until_request_id is not None and payload.get("request_id") == until_request_id:
                return payload


def detail(result: dict) -> str:
    """Pull the human-readable message out of the nested result_details shape."""
    details = result.get("result_details")
    if isinstance(details, dict):
        entries = details.get("result_details", [])
        if entries:
            return "; ".join(str(entry.get("message", entry)) for entry in entries)
    return str(details)


def report(label: str, reply: dict, *, expect_failure: bool = False) -> bool:
    """Print one outcome. Returns True when it matched expectations."""
    body = reply.get("result", {})
    succeeded = reply.get("event_type") == "EventResultSuccess"
    passed = succeeded is not expect_failure
    print(f"\n[{'PASS' if passed else 'FAIL'}] {label}")
    print(f"       result_type : {reply.get('result_type', '?')}")
    print(f"       details     : {detail(body)[:200]}")
    noise = {"result_type", "result_details", "altered_workflow_state", "exception", "traceback"}
    visible = {k: v for k, v in body.items() if k not in noise}
    if visible:
        print(f"       payload     : {json.dumps(visible, default=str)[:320]}")
    return passed


async def main() -> int:  # noqa: PLR0915
    print(f"connecting to {WS_URL}")

    async with connect(WS_URL, max_size=None) as ws:
        client = NukeClient(ws)
        await client.subscribe(REPLY_TOPIC)
        checks: list[bool] = []

        # 1. Connect
        connected = await client.request(
            "NukeConnectRequest", {"client_protocol_versions": [1], "client_name": "reference client"}
        )
        checks.append(report("connect: negotiate protocol and receive the event topic", connected))
        event_topic = connected.get("result", {}).get("event_topic")
        if not event_topic:
            print("\ncannot continue: no event topic returned")
            return 1
        await client.subscribe(event_topic)
        print(f"       subscribed to notifications on '{event_topic}'")

        checks.append(
            report(
                "connect: unsupported protocol version is refused",
                await client.request("NukeConnectRequest", {"client_protocol_versions": [99]}),
                expect_failure=True,
            )
        )

        # 2. Discover
        listed = await client.request("NukeListWorkflowsRequest", {"runnable_only": True})
        checks.append(report("discover: list runnable workflows", listed))
        workflows = listed.get("result", {}).get("workflows", [])

        described = None
        if workflows:
            described = await client.request("NukeDescribeWorkflowRequest", {"workflow_id": workflows[0]["id"]})
            checks.append(report("discover: describe ports as host types", described))

        checks.append(
            report(
                "discover: unknown workflow id fails cleanly",
                await client.request("NukeDescribeWorkflowRequest", {"workflow_id": "does-not-exist"}),
                expect_failure=True,
            )
        )

        # 3 and 4. Run, then listen for pushed node state and parameter value events.
        #
        # A missing runnable workflow must fail rather than skip. Silently dropping these
        # checks would leave the suite green while the run and listen paths went untested,
        # which is exactly how a broken integration looks healthy.
        if described is None:
            print("\n[FAIL] run and listen: no runnable workflow is registered")
            print("       NukeListWorkflowsRequest(runnable_only=True) returned nothing, so")
            print("       there is nothing to execute. Register a workflow with a Start Flow")
            print("       and End Flow pair, then re-run.")
            checks.append(False)
        else:
            inputs: dict[str, dict[str, Any]] = {}
            for port in described.get("result", {}).get("inputs", []):
                if port["type"] == "GTText":
                    inputs.setdefault(port["node"], {})[port["parameter"]] = "nuke api smoke test"

            started = await client.request(
                "NukeExecuteWorkflowRequest", {"workflow_id": workflows[0]["id"], "inputs": inputs}
            )
            run_started = report("run: start a workflow with inputs", started)
            checks.append(run_started)

            if run_started:
                # Collect notifications without sending a single request, so a pass here
                # cannot be explained by polling. If this yields nothing, the push path is
                # broken no matter what the poll verb later reports.
                await client.drain(RUN_TIMEOUT_S)

                node_events = [n for n in client.notifications if n["type"] == "NukeNodeStateEvent"]
                value_events = [n for n in client.notifications if n["type"] == "NukeParameterValueEvent"]
                execution_events = [n for n in client.notifications if n["type"] == "NukeExecutionStateEvent"]

                print(f"\n[{'PASS' if node_events else 'FAIL'}] listen: node state events arrive unsolicited")
                print(f"       received    : {len(node_events)} (no request was sent)")
                for event in node_events[:5]:
                    body = event["body"]
                    print(f"       {body.get('state'):10} {body.get('node_name')}")
                checks.append(bool(node_events))

                declared_types = set(connected["result"]["value_types"])
                escaped = [
                    n for n in value_events if n["body"].get("value", {}).get("value_type") not in declared_types
                ]
                print(
                    f"\n[{'PASS' if value_events and not escaped else 'FAIL'}] listen: parameter value events arrive normalized"
                )
                print(f"       received    : {len(value_events)}")
                for event in value_events[:5]:
                    body = event["body"]
                    print(
                        f"       {body.get('value', {}).get('value_type'):10} {body.get('node_name')}.{body.get('parameter_name')}"
                    )
                if escaped:
                    print(f"       ESCAPED     : {[n['body']['value']['value_type'] for n in escaped]}")
                checks.append(bool(value_events) and not escaped)

                print(f"\n[{'PASS' if execution_events else 'FAIL'}] listen: terminal execution event")
                for event in execution_events:
                    body = event["body"]
                    print(
                        f"       {body.get('state'):10} terminal_node={body.get('terminal_node')!r} {body.get('detail', '')[:50]}"
                    )
                checks.append(bool(execution_events))

                # Recovery: read outputs from the engine, which is also what a host does
                # after reconnecting having missed every event. Outputs must match the
                # ports describe promised, not whatever node control flow ended on.
                recovered = await client.request("NukeGetExecutionStateRequest", {"include_outputs": True})
                recovered_ok = report("recover: read declared outputs with no events", recovered)
                polled = recovered.get("result", {}).get("outputs", {})
                promised = {port["node"] for port in described["result"]["outputs"]}
                matches_contract = promised.issubset(set(polled))
                print(f"       describe promised : {sorted(promised)}")
                print(f"       engine returned   : {sorted(polled)}")
                print(f"       matches contract  : {'yes' if matches_contract else 'no'}")
                checks.append(recovered_ok and matches_contract)

        checks.append(
            report(
                "cancel: refused cleanly when nothing is running",
                await client.request("NukeCancelExecutionRequest"),
                expect_failure=True,
            )
        )

        # Additive-change safety: a field this build predates must be ignored.
        checks.append(
            report(
                "compat: unknown request field is ignored",
                await client.request(
                    "NukeConnectRequest",
                    {"client_protocol_versions": [1], "field_from_a_future_version": "ignore me"},
                ),
            )
        )

        print(f"\n{sum(checks)}/{len(checks)} checks passed")
        print(f"notifications observed: {len(client.notifications)}")
        return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
