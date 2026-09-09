// Notification ingestion: engine push in, panel state out.
//
// Imports no actions. The terminal case needs work this module has no business owning (stop
// polling, read outputs, close the run log entry), so main.js registers that as a hook.
const Events = (function () {
  const { NOTIFICATION, isTerminal } = Protocol;
  const { LIVE_FEED_LIMIT } = Config;
  const { setState, state } = Store;
  const { paramKey } = Values;

  const hooks = { onTerminal: () => {} };

  function setEventHooks(next) {
    Object.assign(hooks, next);
  }

  function dispatchNotification(payloadType, body) {
    const patch = { notifications: state().notifications.concat([{ type: payloadType, body }]) };

    if (payloadType === NOTIFICATION.NODE_STATE) {
      const nodeStates = state().nodeStates.slice();
      const index = nodeStates.findIndex((entry) => entry.node === body.node_name);
      const entry = { node: body.node_name, state: body.state, detail: body.detail || "" };
      if (index === -1) nodeStates.push(entry);
      else nodeStates[index] = entry;
      patch.nodeStates = nodeStates;
    } else if (payloadType === NOTIFICATION.PARAMETER_VALUE) {
      // The engine pushes both sides, so route by what the loaded workflow declared rather than
      // assuming every streamed value is an output.
      const key = paramKey(body.node_name, body.parameter_name);
      const declaredInput = ((state().loaded && state().loaded.inputs) || []).some(
        (param) => paramKey(param.node, param.parameter) === key,
      );
      const target = declaredInput ? "inputValues" : "outputValues";
      patch[target] = Object.assign({}, state()[target]);
      patch[target][key] = { value: body.value, live: true };
    } else if (payloadType === NOTIFICATION.EXECUTION_NODES) {
      // One non-empty list per flow the engine starts, so arrival order is what tells the run's
      // total from a subflow's. The empty list marks top-level completion.
      const involved = Array.isArray(body.involved_nodes) ? body.involved_nodes : [];
      patch.executionNodeSets = state().executionNodeSets.concat([involved]);
      if (involved.length && state().runTotal === null) patch.runTotal = involved;
    } else if (payloadType === NOTIFICATION.EXECUTION_STATE) {
      patch.execution = body;
      if (isTerminal(body.state)) {
        patch.runActive = false;
        patch.runEndedAt = Date.now();
      }
    }

    setState(patch);
    noteEvent(payloadType, body);

    if (payloadType === NOTIFICATION.EXECUTION_STATE && isTerminal(body.state)) {
      hooks.onTerminal(body);
    }
    // An unknown Nuke* notification is logged and ignored rather than treated as fatal.
  }

  /* --------------------------------------------------------------------- the feed */

  // Origin is inferred from whether this panel sent the run request: the protocol carries no
  // execution id to attribute an event with.
  function noteRunActivity(startedHere) {
    if (state().runActive) return;
    setState({
      runActive: true,
      runOrigin: startedHere ? "this panel" : "elsewhere",
      runStartedAt: Date.now(),
      runEndedAt: null,
      requestsDuringRun: 0,
    });
  }

  // Only events that mean work is starting arm a foreign run, so a terminal event or a trailing
  // value cannot re-arm a run that just finished.
  function armsAForeignRun(payloadType, body) {
    if (payloadType === NOTIFICATION.NODE_STATE) {
      return body.state === "running" || body.state === "unresolved";
    }
    if (payloadType === NOTIFICATION.EXECUTION_NODES) {
      return Array.isArray(body.involved_nodes) && body.involved_nodes.length > 0;
    }
    return false;
  }

  function noteEvent(payloadType, body) {
    const now = Date.now();
    const delta = state().lastEventAt ? now - state().lastEventAt : null;
    if (armsAForeignRun(payloadType, body)) noteRunActivity(false);

    const feed = state().feed.concat([
      {
        delta,
        type: payloadType,
        summary: summarizeEvent(payloadType, body),
        foreign: state().runOrigin === "elsewhere",
        at: now,
      },
    ]);
    setState({
      lastEventAt: now,
      feed: feed.length > LIVE_FEED_LIMIT ? feed.slice(feed.length - LIVE_FEED_LIMIT) : feed,
    });
  }

  function summarizeEvent(payloadType, body) {
    if (payloadType === NOTIFICATION.NODE_STATE) {
      return (
        (body.state || "?") +
        "  " +
        (body.node_name || "?") +
        (body.detail ? "  " + body.detail : "")
      );
    }
    if (payloadType === NOTIFICATION.PARAMETER_VALUE) {
      return (
        ((body.value || {}).value_type || "?") +
        "  " +
        paramKey(body.node_name, body.parameter_name)
      );
    }
    if (payloadType === NOTIFICATION.EXECUTION_STATE) {
      return (body.state || "?") + "  terminal_node=" + (body.terminal_node || "-");
    }
    if (payloadType === NOTIFICATION.EXECUTION_NODES) {
      const involved = Array.isArray(body.involved_nodes) ? body.involved_nodes : [];
      if (!involved.length) return "empty list, the top-level run finished";
      return involved.length + " node(s)  " + involved.join(", ");
    }
    return JSON.stringify(body).slice(0, 120);
  }

  return {
    setEventHooks,
    dispatchNotification,
    noteRunActivity,
  };
})();
