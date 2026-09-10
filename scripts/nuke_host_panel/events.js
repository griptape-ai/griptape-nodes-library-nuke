// main.js registers terminal actions here to avoid an Actions dependency.
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
      // Route streamed values using the loaded declaration; the engine pushes inputs and outputs.
      const key = paramKey(body.node_name, body.parameter_name);
      const declaredInput = ((state().loaded && state().loaded.inputs) || []).some(
        (param) => paramKey(param.node, param.parameter) === key,
      );
      const target = declaredInput ? "inputValues" : "outputValues";
      patch[target] = Object.assign({}, state()[target]);
      patch[target][key] = { value: body.value, live: true };
    } else if (payloadType === NOTIFICATION.EXECUTION_NODES) {
      // The first non-empty list is the run total; later lists are subflows. Empty ends the top
      // flow.
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
    // Ignore unknown Nuke notifications after logging them.
  }

  // The protocol has no execution id, so origin is inferred from local run requests.
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

  // Only start events arm a foreign run; terminal or trailing values must not re-arm one.
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
