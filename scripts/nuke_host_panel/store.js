// One store, because the socket mutates state from callbacks that are outside any component.
// Renders are coalesced to one per frame: a burst of parameter value events in the same
// millisecond would otherwise render once each.
//
// Framework-free on purpose. ui/common.js turns the listener API below into a Preact hook.
const Store = (function () {
  const { DEFAULT_CLIENT_NAME, DEFAULT_WS_URL, SETTINGS_KEY } = Config;

  function readSettings() {
    try {
      const parsed = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "null");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  const saved = readSettings();

  const listeners = new Set();
  let scheduled = false;

  const store = {
    state: {
      // connection
      wsUrl: saved.wsUrl || DEFAULT_WS_URL,
      clientName: saved.clientName || DEFAULT_CLIENT_NAME,
      socket: "disconnected",
      session: null,
      subscribed: { reply: false, events: false },
      autoConnect: true,
      connectAttempts: 0,
      reconnects: 0,
      nextAttemptAt: null,
      resyncSteps: [],
      // projects
      projects: [],
      currentProject: null,
      describedProject: null,
      projectChoice: "",
      includeSystemBuiltins: Boolean(saved.includeSystemBuiltins),
      projectNote: "",
      // workflows
      workflows: [],
      described: null,
      loaded: null,
      loadFilePath: "",
      restored: 0,
      // values
      fields: {},
      writeThrough: saved.writeThrough !== false,
      inputValues: {},
      outputValues: {},
      lastSet: null,
      // execution
      execution: null,
      nodeStates: [],
      executionNodeSets: [],
      runTotal: null,
      runActive: false,
      runOrigin: null,
      runStartedAt: null,
      runEndedAt: null,
      pollTicks: 0,
      pollSummary: "",
      history: [],
      viewingRun: null,
      // instrumentation
      banner: null,
      notifications: [],
      feed: [],
      frames: [],
      frameFilter: "",
      requestsSent: 0,
      requestsDuringRun: 0,
      lastEventAt: null,
      // ui
      drawerOpen: Boolean(saved.drawerOpen),
      drawerTab: saved.drawerTab || "connection",
      engines: saved.engines && typeof saved.engines === "object" ? saved.engines : {},
      tick: 0,
    },
  };

  const state = () => store.state;

  function setState(patch) {
    Object.assign(store.state, patch);
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      listeners.forEach((listener) => listener());
    });
  }

  function subscribeToStore(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  function banner(kind, title, text) {
    setState({ banner: { kind, title, text } });
  }

  // Every action goes through this, so a rejected promise becomes a message rather than a silent
  // console error.
  function guard(fn) {
    return async () => {
      try {
        await fn();
      } catch (err) {
        banner("bad", "Request failed.", String(err && err.message ? err.message : err));
      }
    };
  }

  /* ------------------------------------------------------------------ preferences */

  function persist() {
    const st = store.state;
    try {
      localStorage.setItem(
        SETTINGS_KEY,
        JSON.stringify({
          wsUrl: st.wsUrl,
          clientName: st.clientName,
          includeSystemBuiltins: st.includeSystemBuiltins,
          writeThrough: st.writeThrough,
          drawerOpen: st.drawerOpen,
          drawerTab: st.drawerTab,
          engines: st.engines,
        }),
      );
    } catch {
      // Storage disabled loses preferences and nothing else.
    }
  }

  // Preferences are per engine: two engines have two sets of workflows, and a workflow id from one
  // means nothing on the other. engine_id is empty on an engine that has not set one, so the URL is
  // the fallback key.
  function engineKey() {
    return (store.state.session || {}).engine_id || store.state.wsUrl;
  }

  function remembered() {
    return store.state.engines[engineKey()] || { lastWorkflowId: "", fields: {} };
  }

  function remember(patch) {
    const key = engineKey();
    const engines = Object.assign({}, store.state.engines);
    engines[key] = Object.assign({ lastWorkflowId: "", fields: {} }, engines[key], patch);
    setState({ engines });
    persist();
  }

  function rememberFields(workflowId, fields) {
    if (!workflowId) return;
    const byWorkflow = Object.assign({}, remembered().fields);
    byWorkflow[workflowId] = fields;
    remember({ fields: byWorkflow });
  }

  return {
    store,
    state,
    setState,
    subscribeToStore,
    banner,
    guard,
    persist,
    remembered,
    remember,
    rememberFields,
  };
})();
