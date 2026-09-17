// Reconnect automatically because restarts, library reloads, and wakeups all close the socket.
const Session = (function () {
  const { CLIENT_PROTOCOL_VERSIONS, VERB } = Protocol;
  const { CONNECT_TIMEOUT_MS, RECONNECT_BACKOFF_MS, REPLY_TOPIC } = Config;
  const { banner, guard, remembered, setState, state } = Store;
  const { closeSocket, detailOf, isOpen, openSocket, request, subscribe, succeeded } = Transport;
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

  function onSocketClosed(event) {
    const wasConnected = state().session !== null;
    const standingDown = state().standingDown;
    stopPolling();
    setState({
      // A stand-down is deliberate, so it must not read like the close code of a crash.
      socket: standingDown
        ? "stood down"
        : "disconnected" + (event && event.code ? " (" + event.code + ")" : ""),
      session: null,
      subscribed: { reply: false, events: false },
      runActive: false,
      standingDown: false,
    });
    // Standing down already explained itself, and its banner must survive this close.
    if (wasConnected && !standingDown) {
      setState({ reconnects: state().reconnects + 1 });
      banner(
        "warn",
        "Socket closed.",
        "Notifications sent while disconnected were lost. Resync reads current state.",
      );
    }
    scheduleReconnect();
  }

  // The engine cannot close this socket, so a displaced host closes its own.
  function standDown(body) {
    stopPolling();
    cancelReconnect();
    setState({ autoConnect: false, standingDown: true, heldBy: body.replaced_by || null });
    closeSocket(1000, "displaced by another host");
    banner(
      "warn",
      "The engine asked this host to disconnect.",
      (body.reason || "Another host took this engine.") + " Take over to claim it back.",
    );
  }

  function noteStep(label, outcome, detail) {
    setState({
      resyncSteps: state().resyncSteps.concat([{ label, outcome, detail: detail || "" }]),
    });
  }

  // Subscribe before requesting so replies are not lost. Read the project before its workflow list.
  async function resync(options) {
    const force = Boolean(options && options.force);
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
          force,
        },
        CONNECT_TIMEOUT_MS,
      );
    } catch (err) {
      // Missing request handlers drop requests without replying.
      noteStep("negotiate a protocol version", "bad", "no reply at all");
      setState({ socket: "no reply" });
      banner(
        "bad",
        "The socket opened, but the connect verb was never answered.",
        err.message +
          ". The library may be unregistered or loaded in a worker instead of the orchestrator.",
      );
      // Retry because a library reload can install the handler without restarting the engine.
      closeSocket(4001, "handshake unanswered");
      return false;
    }

    if (!succeeded(reply)) {
      const refusal = reply.result || {};
      // A held engine is refused by name; nothing else in this reply says which refusal it was.
      if (refusal.host_client_name) {
        noteStep("claim the engine", "bad", "held by " + refusal.host_client_name);
        setState({ socket: "held", heldBy: refusal.host_client_name });
        banner(
          "warn",
          "Another host is driving this engine.",
          detailOf(reply) + " Take over from the connection drawer.",
        );
        return false;
      }
      const supported = refusal.supported_protocol_versions || [];
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
    // engine_version is display-only; branch only on negotiated protocol_version.
    setState({
      socket: "connected",
      session: result,
      banner: null,
      connectAttempts: 0,
      heldBy: null,
    });
    noteStep(
      "negotiate a protocol version",
      "ok",
      "version " + result.protocol_version + ", engine " + (result.engine_name || "unnamed"),
    );
    // A displaced host keeps its socket and its feed, so say so rather than reporting a clean claim.
    if (result.displaced_client_name) {
      noteStep("claim the engine", "warn", "took it from " + result.displaced_client_name);
      banner(
        "warn",
        "Took the engine from " + result.displaced_client_name + ".",
        "That host is still connected and can still drive this engine.",
      );
    } else {
      noteStep("claim the engine", "ok", result.host_client_name || "");
    }

    // event_topic is not derivable; without it notifications fail silently.
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

  // Query loaded state without loading because load would discard an existing graph.
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
      // Rebuild declarations and values from the engine rather than local memory.
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
    noteStep("re-read values", "ok", "notifications have no replay");

    if (running) {
      noteRunActivity(false);
      // Keep an empty total as null so event and poll paths can fill it.
      const involved = (settled.result || {}).involved_nodes || [];
      setState({ runTotal: involved.length ? involved : null });
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

  // A refused claim leaves the socket open, so a takeover is one more handshake on it.
  async function doTakeOver() {
    if (!isOpen()) {
      await doConnect();
      // The claim may have been free by then, leaving nothing to take.
      if (state().session) {
        setState({ autoConnect: true });
        return;
      }
      // doConnect() failed to open a socket; resync() below would throw instead of refusing.
      if (!isOpen()) return;
    }
    const tookOver = await resync({ force: true });
    // Taking over is an explicit reconnect, so retry goes back on whatever turned it off.
    if (tookOver) setState({ autoConnect: true });
  }

  function doDisconnect() {
    setState({ autoConnect: false });
    cancelReconnect();
    closeSocket(1000, "host closing");
  }

  function doDropSocket() {
    setState({ autoConnect: true });
    closeSocket(4000, "recovery drill");
  }

  return {
    onSocketClosed,
    resync,
    doConnect,
    doTakeOver,
    standDown,
    doDisconnect,
    doDropSocket,
    cancelReconnect,
  };
})();
