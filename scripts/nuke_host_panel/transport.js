const Transport = (function () {
  const { FRAME_LOG_LIMIT, REPLY_TOPIC, REQUEST_TIMEOUT_MS } = Config;
  const { setState, state } = Store;

  let ws = null;
  const pending = new Map();
  const handlers = { onNotification: () => {}, onClose: () => {} };

  function setHandlers(next) {
    Object.assign(handlers, next);
  }

  const isOpen = () => Boolean(ws) && ws.readyState === WebSocket.OPEN;

  function logFrame(direction, frame) {
    const payload = (frame && frame.payload) || {};
    const frames = state().frames.concat([
      {
        direction,
        at: new Date(),
        type: frame && frame.type ? frame.type : payload.event_type || "?",
        what:
          payload.request_type || payload.payload_type || payload.result_type || frame.topic || "",
        requestId: payload.request_id || frame.id || "",
        frame,
      },
    ]);
    setState({
      frames:
        frames.length > FRAME_LOG_LIMIT ? frames.slice(frames.length - FRAME_LOG_LIMIT) : frames,
    });
  }

  function sendFrame(frame) {
    if (!isOpen()) throw new Error("Socket is not open.");
    ws.send(JSON.stringify(frame));
    logFrame("out", frame);
  }

  function subscribe(topic) {
    sendFrame({ type: "subscribe", topic });
  }

  // Correlate by request_id because notifications interleave with replies.
  function newRequestId() {
    return Math.random().toString(16).slice(2) + Date.now().toString(16);
  }

  // Batch requests register several replies before sending one frame.
  function trackReply(requestId, requestType, timeoutMs) {
    const budget = timeoutMs === undefined ? REQUEST_TIMEOUT_MS : timeoutMs;
    return new Promise((resolve, reject) => {
      // Zero disables the timeout for execute requests that span a run.
      const timer = budget
        ? setTimeout(() => {
            pending.delete(requestId);
            reject(
              new Error(
                "Timed out after " + budget / 1000 + "s waiting for a reply to " + requestType,
              ),
            );
          }, budget)
        : null;
      pending.set(requestId, { resolve, reject, timer });
    });
  }

  function forget(requestId) {
    const entry = pending.get(requestId);
    if (!entry) return;
    clearTimeout(entry.timer);
    pending.delete(requestId);
  }

  function countRequest() {
    setState({
      requestsSent: state().requestsSent + 1,
      requestsDuringRun: state().runActive
        ? state().requestsDuringRun + 1
        : state().requestsDuringRun,
    });
  }

  function requestEnvelope(requestType, payload, requestId) {
    return {
      event_type: "EventRequest",
      request_type: requestType,
      request: payload || {},
      request_id: requestId,
      response_topic: REPLY_TOPIC,
    };
  }

  function request(requestType, payload, timeoutMs) {
    const requestId = newRequestId();
    const waiting = trackReply(requestId, requestType, timeoutMs);
    countRequest();
    try {
      sendFrame({ payload: requestEnvelope(requestType, payload, requestId) });
    } catch (err) {
      forget(requestId);
      return Promise.reject(err);
    }
    return waiting;
  }

  // Inner batch requests keep independent ids and receive ordinary result frames.
  // EventRequestBatch belongs to the engine wire format, not this versioned protocol.
  function requestBatch(entries, timeoutMs) {
    const requests = [];
    const waiting = entries.map((entry) => {
      const requestId = newRequestId();
      requests.push(requestEnvelope(entry.requestType, entry.payload, requestId));
      return trackReply(requestId, entry.requestType, timeoutMs);
    });
    countRequest();
    try {
      sendFrame({ payload: { event_type: "EventRequestBatch", requests } });
    } catch (err) {
      requests.forEach((envelope) => forget(envelope.request_id));
      return Promise.reject(err);
    }
    return Promise.all(waiting);
  }

  // Dispatch every socket frame; scanning only for a reply would drop interleaved notifications.
  function onMessage(event) {
    let frame;
    try {
      frame = JSON.parse(event.data);
    } catch {
      logFrame("in", {
        type: "unparseable",
        payload: { request_type: String(event.data).slice(0, 200) },
      });
      return;
    }
    logFrame("in", frame);
    const payload = frame.payload || {};

    if (frame.type === "pong") return;

    if (frame.type === "app_event" || payload.event_type === "AppEvent") {
      const payloadType = payload.payload_type || "";
      // Other libraries and the engine broadcast on this topic too.
      if (payloadType.indexOf("Nuke") === 0) {
        handlers.onNotification(payloadType, payload.payload || {});
      }
      return;
    }

    const waiting = pending.get(payload.request_id);
    if (waiting) {
      clearTimeout(waiting.timer);
      pending.delete(payload.request_id);
      waiting.resolve(payload);
      return;
    }
    // Ignore uncorrelated engine traffic to avoid depending on internal wire formats.
  }

  function openSocket(url) {
    return new Promise((resolve, reject) => {
      let socket;
      try {
        socket = new WebSocket(url);
      } catch (err) {
        reject(err);
        return;
      }
      socket.onopen = () => {
        ws = socket;
        resolve();
      };
      socket.onerror = () =>
        reject(
          new Error(
            "Could not open " +
              url +
              ". Is the engine running with the websocket_direct driver enabled?",
          ),
        );
      socket.onclose = (event) => {
        ws = null;
        pending.forEach((entry) => clearTimeout(entry.timer));
        pending.clear();
        handlers.onClose(event);
      };
      socket.onmessage = onMessage;
    });
  }

  function closeSocket(code, reason) {
    if (ws) ws.close(code, reason);
  }

  const succeeded = (reply) => Boolean(reply) && reply.event_type === "EventResultSuccess";

  // Failure messages are written to be displayed, so they are used verbatim.
  function detailOf(reply) {
    const result = (reply && reply.result) || {};
    const details = result.result_details;
    if (details && Array.isArray(details.result_details)) {
      const messages = details.result_details.map(
        (entry) => (entry && entry.message) || JSON.stringify(entry),
      );
      if (messages.length) return messages.join("; ");
    }
    if (typeof details === "string") return details;
    return "";
  }

  return {
    setHandlers,
    isOpen,
    subscribe,
    request,
    requestBatch,
    openSocket,
    closeSocket,
    succeeded,
    detailOf,
  };
})();
