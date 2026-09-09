// Connection lifecycle: connect, resync, reconnect, and adopting whatever the engine already holds.
//
// Why this auto-connects rather than waiting for a button: an engine restart, a library reload after
// a project switch, and a laptop waking up all arrive as a closed socket, so reconnecting is the
// normal case.
const Session = (function () {
  const { CLIENT_PROTOCOL_VERSIONS, VERB } = Protocol;
  const { CONNECT_TIMEOUT_MS, RECONNECT_BACKOFF_MS, REPLY_TOPIC } = Config;
  const { banner, guard, remembered, setState, state } = Store;
  const { closeSocket, detailOf, openSocket, request, subscribe, succeeded } = Transport;
  const { noteRunActivity } = Events;
  const {
    doDescribe,
    doList,
    doListProjects,
    doReadCurrentProject,
    doReadValues,
    seedFields,
    startPolling,
    stopPolling,
  } = Actions;
  const { unflatten } = Values;

  let reconnectTimer = null;

  function cancelReconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    setState({ nextAttemptAt: null });
  }

  function scheduleReconnect() {
    cancelReconnect();
    if (!state().autoConnect) return;
    const attempt = state().connectAttempts;
    const delay = RECONNECT_BACKOFF_MS[Math.min(attempt, RECONNECT_BACKOFF_MS.length - 1)];
    setState({ nextAttemptAt: Date.now() + delay });
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      setState({ nextAttemptAt: null });
      guard(doConnect)();
    }, delay);
  }

  // Registered as the transport's close handler.
  function onSocketClosed(event) {
    const wasConnected = state().session !== null;
    stopPolling();
    setState({
      socket: "disconnected" + (event && event.code ? " (" + event.code + ")" : ""),
      session: null,
      subscribed: { reply: false, events: false },
      runActive: false,
    });
    if (wasConnected) {
      setState({ reconnects: state().reconnects + 1 });
      banner(
        "warn",
        "Socket closed.",
        "Notifications sent while disconnected are gone: no buffer, no backlog, no resume cursor. " +
          "The resync sequence re-reads current truth instead.",
      );
    }
    scheduleReconnect();
  }

  function noteStep(label, outcome, detail) {
    setState({
      resyncSteps: state().resyncSteps.concat([{ label, outcome, detail: detail || "" }]),
    });
  }

  // One sequence for first connect, reconnect, and page reload. A host with a separate startup path
  // and recovery path has two paths and only ever tests one.
  //
  // Order is load-bearing. Subscribe before requesting, or the reply is published to a topic this
  // connection is not listening on. Read the project before the workflow list, because workflows are
  // registered per workspace and a project decides the workspace.
  async function resync() {
    setState({ resyncSteps: [] });

    subscribe(REPLY_TOPIC);
    setState({ subscribed: { reply: true, events: false } });
    noteStep("subscribe to the reply topic", "ok", REPLY_TOPIC);

    let reply;
    try {
      reply = await request(
        VERB.CONNECT,
        {
          client_protocol_versions: CLIENT_PROTOCOL_VERSIONS,
          client_name: state().clientName.trim() || "browser host",
        },
        CONNECT_TIMEOUT_MS,
      );
    } catch (err) {
      // No reply is a different diagnosis from a refusal: the engine drops a request type it has no
      // handler for without answering, so silence means the verb's owner is missing.
      noteStep("negotiate a protocol version", "bad", "no reply at all");
      setState({ socket: "no reply" });
      banner(
        "bad",
        "The socket opened, but the connect verb was never answered.",
        err.message +
          ". The engine is reachable, so the likely cause is that this library is not installed in " +
          "it: an unhandled request type gets silence rather than a failure. Check that the library " +
          "is registered, and that it loaded in the orchestrator process rather than a worker.",
      );
      // Keep trying: a project switch reloads libraries, so verbs this engine does not answer now can
      // appear without a restart.
      closeSocket(4001, "handshake unanswered");
      return false;
    }

    if (!succeeded(reply)) {
      const supported = (reply.result && reply.result.supported_protocol_versions) || [];
      noteStep(
        "negotiate a protocol version",
        "bad",
        "library supports " + JSON.stringify(supported),
      );
      setState({ socket: "refused" });
      banner(
        "bad",
        "The library refused this protocol version.",
        detailOf(reply) + " Library supports: " + JSON.stringify(supported),
      );
      return false;
    }

    const result = reply.result || {};
    // protocol_version is the highest version both sides know. engine_version is display only and
    // must never be branched on.
    setState({ socket: "connected", session: result, banner: null, connectAttempts: 0 });
    noteStep(
      "negotiate a protocol version",
      "ok",
      "version " + result.protocol_version + ", engine " + (result.engine_name || "unnamed"),
    );

    // The event topic is not derivable. Miss this and replies arrive but notifications silently do
    // not.
    if (result.event_topic) {
      subscribe(result.event_topic);
      setState({ subscribed: { reply: true, events: true } });
      noteStep("subscribe to the event topic", "ok", result.event_topic);
    } else {
      noteStep("subscribe to the event topic", "bad", "none reported");
    }

    await doReadCurrentProject();
    noteStep(
      "read the current project",
      state().currentProject ? "ok" : "bad",
      (state().currentProject && state().currentProject.workspace_dir) || "",
    );

    await doListProjects();
    await doList();
    noteStep("list workflows for that workspace", "ok", state().workflows.length + " listed");

    await adoptWhateverIsLoaded();
    return true;
  }

  // The engine may hold a graph this panel did not load: a bare reconnect kept the one it had, an
  // engine restart lost it, and a page reload forgot it either way. Ask rather than assume, and never
  // load to find out, because loading discards whatever is there.
  async function adoptWhateverIsLoaded() {
    const held = state().loaded;
    const settled = await request(VERB.GET_EXECUTION_STATE, {});
    const engineHolds = succeeded(settled) ? (settled.result || {}).workflow_id || "" : "";
    const running = succeeded(settled) && (settled.result || {}).running === true;

    if (!engineHolds) {
      noteStep(
        "ask what the engine holds",
        held ? "warn" : "ok",
        held ? "nothing, so the values on screen drove nothing and were dropped" : "nothing",
      );
      setState({ loaded: null, fields: {}, inputValues: {}, outputValues: {} });
      // Describe the last workflow, which reads the registry and changes no engine state.
      const last = remembered().lastWorkflowId;
      if (last && state().workflows.some((workflow) => workflow.id === last)) {
        await doDescribe(last);
        noteStep("restore the last workflow", "ok", "described, not loaded");
      }
      return;
    }

    if (held && held.workflow_id === engineHolds) {
      noteStep("ask what the engine holds", "ok", engineHolds + ", the one on screen");
    } else {
      // Rebuild from the engine rather than from memory: the declaration from the registry, the
      // values from the loaded graph.
      const describe = await request(VERB.DESCRIBE_WORKFLOW, { workflow_id: engineHolds });
      if (!succeeded(describe)) {
        noteStep("adopt the loaded workflow", "bad", detailOf(describe));
        return;
      }
      const described = describe.result || {};
      setState({ loaded: described, described, nodeStates: [], execution: null });
      noteStep("adopt the workflow the engine holds", "ok", engineHolds);
    }

    await doReadValues();
    const declared = (state().loaded && state().loaded.inputs) || [];
    const seeded = seedFields(declared, unflatten(state().inputValues), engineHolds);
    setState({ fields: seeded.fields, restored: seeded.restored });
    noteStep("re-read values", "ok", "notifications have no replay, so this is the way back");

    if (running) {
      noteRunActivity(false);
      setState({ runTotal: (settled.result || {}).involved_nodes || null });
      startPolling();
      noteStep("a run is already in flight", "warn", "joined it, events resume live");
    }
  }

  async function doConnect() {
    cancelReconnect();
    setState({
      socket: "connecting",
      banner: null,
      connectAttempts: state().connectAttempts + 1,
    });
    try {
      await openSocket(state().wsUrl.trim());
    } catch (err) {
      setState({ socket: "failed" });
      banner("bad", "Connection failed.", err.message);
      scheduleReconnect();
      return;
    }
    setState({ socket: "open" });
    await resync();
  }

  // Closing the panel is not a dropped socket, so this stops the retry loop too.
  function doDisconnect() {
    setState({ autoConnect: false });
    cancelReconnect();
    closeSocket(1000, "host closing");
  }

  // The drill worth running: drop the socket under a live run.
  function doDropSocket() {
    setState({ autoConnect: true });
    closeSocket(4000, "recovery drill");
  }

  return {
    onSocketClosed,
    resync,
    doConnect,
    doDisconnect,
    doDropSocket,
    cancelReconnect,
  };
})();
