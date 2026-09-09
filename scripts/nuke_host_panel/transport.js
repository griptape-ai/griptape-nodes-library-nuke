// Transport. The part a real plugin reimplements: one socket, request/reply correlation, and a
// message pump that dispatches notifications while requests are still outstanding.
//
// Nothing here knows about panes or engine semantics. It reports frames to the store for the wire
// log and hands notifications to whatever handler was registered.
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

  // Correlated by request_id, never by arrival order: notifications share this socket and arrive
  // interleaved.
  function newRequestId() {
    return Math.random().toString(16).slice(2) + Date.now().toString(16);
  }

  // Registering the reply is separate from sending the frame, because a batch registers several
  // replies and sends one frame.
  function trackReply(requestId, requestType, timeoutMs) {
    const budget = timeoutMs || REQUEST_TIMEOUT_MS;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(requestId);
        reject(
          new Error("Timed out after " + budget / 1000 + "s waiting for a reply to " + requestType),
        );
      }, budget);
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

  // Several verbs in one round trip. The engine fans the batch out on ingest, so each inner request
  // keeps its own request_id and its reply arrives as a normal result frame; there is no batched
  // reply to wait for. EventRequestBatch is the engine's own wire envelope, not part of this
  // protocol, so its shape can change without a version bump.
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

  // A client that reads until it finds its own reply, discarding the rest, silently drops every
  // notification. One pump owns the socket.
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
    // Anything else is the engine's own traffic. Binding to it would take on the engine's release
    // cadence, which is the problem this protocol exists to avoid.
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
