"""Live smoke tests for the Nuke host API, run against a real engine over local_socket.

Covers the four capabilities a host needs, in the order a plugin performs them:
discovery, connect, interrogate the start and end flow, execute. Everything the unit
suite proves with mocks is proved here against the real engine instead, because the unit
suite cannot catch a wrong frame envelope, a workflow_shape that arrives as a JSON string,
or a notification that never gets pushed.

Prerequisites, and the tests say so when they are missing rather than passing quietly:

1. `local_socket` enabled in the engine config, and the engine restarted. See
   `nuke_host_api/INTEGRATION.md`.
2. This library registered in that engine.
3. At least one runnable workflow with a Start Flow and End Flow pair. Name a specific one
   with GRIPTAPE_NODES_SMOKE_WORKFLOW, otherwise the first runnable one is used.

    make test/integration/host-api

A skipped execution test means this run proved nothing about execution. Read the skip
reasons, do not read a green summary.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

import pytest

from nuke_host_api.protocol import PROTOCOL_VERSION, VALUE_TYPES, NodeState, Verb
from tests.integration.host_api_client import (
    HostClient,
    detail_of,
    discover,
    engines_registry_path,
    result_of,
    running_engine,
    socket_path_for,
    succeeded,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.integration.host_api_client import Engine

ENGINE = running_engine()
NAMED_WORKFLOW = os.environ.get("GRIPTAPE_NODES_SMOKE_WORKFLOW")
NOTIFICATION_WINDOW_S = float(os.environ.get("GRIPTAPE_NODES_SMOKE_WINDOW_S", "30"))

pytestmark = [
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="local_socket is a named pipe on Windows, which this harness does not open",
    ),
    pytest.mark.skipif(
        ENGINE is None,
        reason=(
            f"No running engine found. Checked {engines_registry_path()} for engine ids and "
            f"looked for a live socket per id. Start an engine with the local_socket IPC "
            f"driver enabled; see nuke_host_api/INTEGRATION.md."
        ),
    ),
]


@pytest.fixture(scope="module")
def engine() -> Engine:
    assert ENGINE is not None
    return ENGINE


@pytest.fixture
def client(engine: Engine) -> Iterator[HostClient]:
    """A connected client that leaves the engine idle behind it.

    Teardown cancels anything still running. Execute refuses to start over a run in
    progress, so one test leaving a flow live would fail every later one for a reason that
    has nothing to do with what they assert.
    """
    with HostClient(socket_path=engine.socket_path) as connected:
        try:
            yield connected
        finally:
            state = connected.request(Verb.GET_EXECUTION_STATE, {"include_outputs": False})
            if succeeded(state) and result_of(state).get("running"):
                connected.request(Verb.CANCEL_EXECUTION)


def _runnable_workflows(client: HostClient) -> list[dict[str, Any]]:
    reply = client.request(Verb.LIST_WORKFLOWS, {"runnable_only": True})
    assert succeeded(reply), f"list workflows failed: {detail_of(reply)}"
    return [entry for entry in result_of(reply).get("workflows", []) if entry.get("runnable")]


def _smoke_workflow_id(client: HostClient) -> str:
    workflows = _runnable_workflows(client)
    if NAMED_WORKFLOW:
        if not any(entry["id"] == NAMED_WORKFLOW for entry in workflows):
            pytest.skip(
                f"GRIPTAPE_NODES_SMOKE_WORKFLOW={NAMED_WORKFLOW!r} is not registered or not "
                f"runnable. Runnable: {[entry['id'] for entry in workflows]}"
            )
        return NAMED_WORKFLOW
    if not workflows:
        pytest.skip(
            "No runnable workflow is registered, so nothing can be executed. Register one "
            "with a Start Flow and End Flow pair. THE EXECUTION PATH WAS NOT TESTED."
        )
    return str(workflows[0]["id"])


# 1. Engine discovery


class TestDiscovery:
    def test_the_registry_lists_engines_and_resolves_a_socket_path_per_engine(self) -> None:
        """Discovery must work with no connection, since it is what finds one."""
        engines = discover()
        assert engines, f"no engines in {engines_registry_path()}"
        for entry in engines:
            assert entry.id
            assert entry.socket_path == socket_path_for(entry.id)
        assert len([entry for entry in engines if entry.is_default]) <= 1

    def test_a_running_engine_is_identified_by_its_socket_existing(self, engine: Engine) -> None:
        assert engine.running
        assert engine.name, "an engine needs a label a host can show an artist"


# 2. Connect


class TestConnect:
    def test_connect_negotiates_a_version_and_returns_the_closed_type_set(self, client: HostClient) -> None:
        reply = client.request(
            Verb.CONNECT, {"client_protocol_versions": [PROTOCOL_VERSION], "client_name": "smoke test"}
        )
        assert succeeded(reply), f"connect failed: {detail_of(reply)}"
        body = result_of(reply)

        assert body["protocol_version"] == PROTOCOL_VERSION
        assert set(body["value_types"]) == set(VALUE_TYPES), (
            "the engine's advertised type set must match this build's closed set"
        )
        assert body["engine_version"] and body["engine_version"] != "unknown"
        assert body["library_version"] != "unknown", "library_version is read from the shipped manifest"
        assert body["event_topic"]

    def test_an_unsupported_protocol_version_is_refused_and_names_the_window(self, client: HostClient) -> None:
        reply = client.request(Verb.CONNECT, {"client_protocol_versions": [99]})
        assert not succeeded(reply)
        assert result_of(reply)["supported_protocol_versions"], "a refusal must tell a host what would work"

    def test_an_unknown_request_field_is_ignored(self, client: HostClient) -> None:
        """Additive change safety, verified rather than asserted in a doc.

        Adding a field must not bump the protocol version, which only holds if an engine
        predating a field tolerates receiving it.
        """
        reply = client.request(
            Verb.CONNECT,
            {"client_protocol_versions": [PROTOCOL_VERSION], "field_from_a_future_version": "ignore me"},
        )
        assert succeeded(reply), f"an unknown field broke connect: {detail_of(reply)}"


# 3. Interrogate the start and end flow


class TestDescribe:
    def test_listed_workflows_carry_an_id_and_a_label(self, client: HostClient) -> None:
        reply = client.request(Verb.LIST_WORKFLOWS, {"runnable_only": False})
        assert succeeded(reply), f"list workflows failed: {detail_of(reply)}"
        workflows = result_of(reply).get("workflows", [])
        if not workflows:
            pytest.skip("this engine has no workflows registered, which is a valid state for an empty workspace")
        for entry in workflows:
            assert entry["id"] and entry["name"]
            if not entry["runnable"]:
                assert entry["unavailable_reason"], "an unrunnable entry must say why"

    def test_every_declared_port_is_completely_described(self, client: HostClient) -> None:
        """A host builds knobs from this, so every field it indexes must be present.

        This is the assertion the mocked suite cannot make: real ports come from a real
        workflow_shape, which arrives as a JSON string for some workflows and is absent for
        others.
        """
        workflow_id = _smoke_workflow_id(client)
        reply = client.request(Verb.DESCRIBE_WORKFLOW, {"workflow_id": workflow_id})
        assert succeeded(reply), f"describe failed: {detail_of(reply)}"
        body = result_of(reply)

        ports = body["inputs"] + body["outputs"]
        assert ports, f"workflow {workflow_id!r} was listed runnable but declares no ports"
        for port in ports:
            assert port["node"] and port["parameter"]
            assert port["name"] == f"{port['node']}.{port['parameter']}"
            assert port["type"] in VALUE_TYPES, f"{port['name']} escaped the closed set with {port['type']!r}"
            assert port["default"]["value_type"] in VALUE_TYPES, f"{port['name']} default is not a descriptor"
            assert isinstance(port["tooltip"], str)
            assert isinstance(port["settable"], bool)

    def test_no_control_flow_port_is_exposed(self, client: HostClient) -> None:
        workflow_id = _smoke_workflow_id(client)
        body = result_of(client.request(Verb.DESCRIBE_WORKFLOW, {"workflow_id": workflow_id}))
        names = [port["parameter"] for port in body["inputs"] + body["outputs"]]
        assert not [name for name in names if name in {"exec_in", "exec_out"}], (
            f"control flow wiring leaked into the host surface: {names}"
        )

    def test_an_unknown_workflow_id_fails_cleanly(self, client: HostClient) -> None:
        reply = client.request(Verb.DESCRIBE_WORKFLOW, {"workflow_id": "does-not-exist"})
        assert not succeeded(reply)
        assert detail_of(reply), "a failure must carry a message an artist can read"


# 4. Execute


class TestExecute:
    def test_a_workflow_runs_and_pushes_node_state_without_being_polled(self, client: HostClient) -> None:
        """The one test that proves push works on this transport.

        Notifications are collected without sending a single request, so a pass cannot be
        explained by polling. local_socket has no subscribe step and the engine's fan-out
        ignores topics for it, so either events arrive unsolicited or the push path is broken.
        """
        workflow_id = _smoke_workflow_id(client)
        started = client.request(Verb.EXECUTE_WORKFLOW, {"workflow_id": workflow_id})
        assert succeeded(started), f"execute failed: {detail_of(started)}"
        assert result_of(started)["rejected_inputs"] == [], "no inputs were sent, so none may be rejected"

        client.drain(NOTIFICATION_WINDOW_S)

        node_events = client.of_type("NukeNodeStateEvent")
        assert node_events, (
            f"no NukeNodeStateEvent arrived in {NOTIFICATION_WINDOW_S}s. Either the execution "
            f"bridge is not installed or push does not reach a local_socket client."
        )
        seen = {event.body["state"] for event in node_events}
        assert seen <= {NodeState.UNRESOLVED, NodeState.RUNNING, NodeState.RESOLVED, NodeState.FAILED}, (
            f"a node state escaped the closed set: {seen}"
        )
        failures = [event.body for event in node_events if event.body["state"] == NodeState.FAILED]
        assert not failures, f"the workflow reported node failures: {failures}"

    def test_streamed_parameter_values_are_already_normalized(self, client: HostClient) -> None:
        """Values on the live path must use the same descriptor shape as describe.

        Also asserts execution wiring stays off the stream. The engine streams a value update
        for exec_in like any other parameter, and a host that received it would be told
        control flow is GTText, contradicting describe_workflow which never lists it.
        """
        workflow_id = _smoke_workflow_id(client)
        assert succeeded(client.request(Verb.EXECUTE_WORKFLOW, {"workflow_id": workflow_id}))
        client.drain(NOTIFICATION_WINDOW_S)

        value_events = client.of_type("NukeParameterValueEvent")
        assert value_events, "no NukeParameterValueEvent arrived, so the value path is untested"
        for event in value_events:
            descriptor = event.body["value"]
            assert descriptor["value_type"] in VALUE_TYPES, (
                f"{event.body['node_name']}.{event.body['parameter_name']} "
                f"escaped the closed set with {descriptor['value_type']!r}"
            )
            assert "sources" in descriptor
            assert "engine_type" in descriptor

        streamed = {f"{event.body['node_name']}.{event.body['parameter_name']}" for event in value_events}
        wiring = {name for name in streamed if name.rsplit(".", 1)[-1] in {"exec_in", "exec_out"}}
        assert not wiring, f"execution wiring reached the host as parameter values: {sorted(wiring)}"

    def test_declared_outputs_are_readable_after_a_run(self, client: HostClient) -> None:
        """The recovery path, and the only definition of outputs in this protocol.

        What it returns must be the ports describe promised, not whichever node control flow
        happened to end on.
        """
        workflow_id = _smoke_workflow_id(client)
        described = result_of(client.request(Verb.DESCRIBE_WORKFLOW, {"workflow_id": workflow_id}))
        assert succeeded(client.request(Verb.EXECUTE_WORKFLOW, {"workflow_id": workflow_id}))
        client.drain(NOTIFICATION_WINDOW_S)

        reply = client.request(Verb.GET_EXECUTION_STATE, {"include_outputs": True})
        assert succeeded(reply), f"reading execution state failed: {detail_of(reply)}"
        body = result_of(reply)
        assert body["workflow_id"] == workflow_id

        promised = {port["node"] for port in described["outputs"]}
        assert promised <= set(body["outputs"]), (
            f"describe promised outputs on {sorted(promised)} but state returned {sorted(body['outputs'])}"
        )
        for parameters in body["outputs"].values():
            for descriptor in parameters.values():
                assert descriptor["value_type"] in VALUE_TYPES

    def test_a_second_run_is_refused_while_one_is_in_progress(self, client: HostClient) -> None:
        """Serial execution is what makes the missing engine-side execution id survivable.

        Skips rather than fails when the first run finishes too fast to race, since that is a
        property of the chosen workflow and not of the guard.
        """
        workflow_id = _smoke_workflow_id(client)
        assert succeeded(client.request(Verb.EXECUTE_WORKFLOW, {"workflow_id": workflow_id}))

        state = result_of(client.request(Verb.GET_EXECUTION_STATE, {"include_outputs": False}))
        if not state.get("running"):
            pytest.skip(f"workflow {workflow_id!r} finished before a second execute could race it")

        second = client.request(Verb.EXECUTE_WORKFLOW, {"workflow_id": workflow_id})
        assert not succeeded(second), "a second run must be refused, not allowed to displace the first"
        assert "already executing" in detail_of(second).lower()

    def test_an_undeclared_input_is_rejected_and_never_reaches_the_graph(self, client: HostClient) -> None:
        """The engine would set a parameter on any node, and this transport authenticates nobody."""
        workflow_id = _smoke_workflow_id(client)
        reply = client.request(
            Verb.EXECUTE_WORKFLOW,
            {"workflow_id": workflow_id, "inputs": {"No Such Node": {"api_key": "stolen"}}},
        )
        assert succeeded(reply), f"execute failed for a reason other than the bad input: {detail_of(reply)}"
        rejected = result_of(reply)["rejected_inputs"]
        assert rejected == [
            {"node": "No Such Node", "parameter": "api_key", "reason": "Not a declared input port of this workflow."}
        ]

    def test_a_declared_input_is_applied(self, client: HostClient) -> None:
        workflow_id = _smoke_workflow_id(client)
        described = result_of(client.request(Verb.DESCRIBE_WORKFLOW, {"workflow_id": workflow_id}))
        text_ports = [port for port in described["inputs"] if port["type"] == "GTText" and port["settable"]]
        if not text_ports:
            pytest.skip(f"workflow {workflow_id!r} has no settable text input to drive")

        port = text_ports[0]
        reply = client.request(
            Verb.EXECUTE_WORKFLOW,
            {"workflow_id": workflow_id, "inputs": {port["node"]: {port["parameter"]: "nuke smoke test"}}},
        )
        assert succeeded(reply), f"execute failed: {detail_of(reply)}"
        body = result_of(reply)
        assert {"node": port["node"], "parameter": port["parameter"]} in body["applied_inputs"]
        assert body["rejected_inputs"] == []


class TestCancel:
    def test_cancel_is_refused_when_nothing_is_running(self, client: HostClient) -> None:
        state = result_of(client.request(Verb.GET_EXECUTION_STATE, {"include_outputs": False}))
        if state.get("running"):
            pytest.skip("something is already running, so an idle cancel cannot be tested")

        reply = client.request(Verb.CANCEL_EXECUTION)
        assert not succeeded(reply), "cancelling nothing must fail rather than silently succeed"
