const Actions = (function () {
  const { VERB } = Protocol;
  const { DRAIN_GRACE_MS, EXECUTE_TIMEOUT_MS, HISTORY_LIMIT, POLL_TICK_MS, WRITE_THROUGH_DEBOUNCE_MS } =
    Config;
  const { banner, guard, remembered, rememberFields, remember, setState, state } = Store;
  const { closeSocket, detailOf, isOpen, request, requestBatch, succeeded } = Transport;
  const { noteRunActivity } = Events;
  const { fieldValueFrom, flattenValues, paramKey } = Values;

  // Prefer graph values, then local values when scalar descriptors omit their values.
  function seedFields(declared, inputValues, workflowId) {
    const previous = remembered().fields[workflowId] || {};
    const fields = {};
    let restored = 0;
    (declared || []).forEach((param) => {
      const key = paramKey(param.node, param.parameter);
      const descriptor = (inputValues || {})[param.node] || {};
      const seed = fieldValueFrom(descriptor[param.parameter]);
      if (seed !== undefined) {
        fields[key] = seed;
      } else if (previous[key] !== undefined && previous[key] !== "") {
        fields[key] = previous[key];
        restored += 1;
      }
    });
    return { fields, restored };
  }

  async function doList() {
    // Include unavailable workflows so their reasons remain visible.
    const reply = await request(VERB.LIST_WORKFLOWS, { runnable_only: false });
    if (!succeeded(reply)) {
      banner("bad", "Listing workflows failed.", detailOf(reply));
      return;
    }
    setState({ workflows: (reply.result && reply.result.workflows) || [] });
  }

  async function doDescribe(workflowId) {
    const reply = await request(VERB.DESCRIBE_WORKFLOW, { workflow_id: workflowId });
    if (!succeeded(reply)) {
      setState({ described: null });
      banner("bad", "Describe failed.", detailOf(reply));
      return;
    }
    setState({ described: reply.result || {}, banner: null });
    remember({ lastWorkflowId: workflowId });
  }

  // Loading clears all engine object state, including graphs opened elsewhere.
  async function doLoad(payload) {
    const holding = state().loaded;
    const described = state().described;
    const naming =
      payload.file_path ||
      (described && described.workflow_id === payload.workflow_id && described.name) ||
      payload.workflow_id;
    const proceed = window.confirm(
      "Load " +
        naming +
        "?\n\nThe engine clears all object state to load a graph, discarding " +
        (holding ? holding.name || holding.workflow_id : "whatever it currently holds") +
        ".",
    );
    if (!proceed) return;

    const reply = await request(VERB.LOAD_WORKFLOW, payload);
    if (!succeeded(reply)) {
      // Trust engine_state_cleared rather than parsing the reason text.
      const cleared = Boolean(reply.result && reply.result.engine_state_cleared);
      if (cleared) setState({ loaded: null, fields: {}, inputValues: {} });
      banner(
        cleared ? "bad" : "warn",
        cleared
          ? "Load failed after the engine had already cleared itself."
          : "Load refused. Nothing changed.",
        detailOf(reply) +
          (cleared
            ? " The graph that was loaded is gone, so its values were dropped."
            : " The loaded graph is untouched, so a retry is free."),
      );
      return;
    }

    const loaded = reply.result || {};
    const seeded = seedFields(loaded.inputs, loaded.input_values, loaded.workflow_id);
    setState({
      loaded,
      described: loaded,
      fields: seeded.fields,
      restored: seeded.restored,
      inputValues: flattenValues(loaded.input_values, false),
      outputValues: flattenValues(loaded.output_values, false),
      nodeStates: [],
      execution: null,
      executionNodeSets: [],
      runTotal: null,
      viewingRun: null,
      loadFilePath: "",
      banner: null,
    });
    remember({ lastWorkflowId: loaded.workflow_id });

    const unavailable = loaded.unavailable || [];
    if (unavailable.length) {
      banner(
        "warn",
        unavailable.length + " declared parameter(s) could not be read.",
        unavailable
          .map(
            (entry) =>
              entry.section + " " + paramKey(entry.node, entry.parameter) + ": " + entry.reason,
          )
          .join(" | "),
      );
    }
  }

  // The wire shape is {node: {parameter: value}}; single edits pass a subset.
  function collectInputs(subset) {
    const inputs = {};
    const declared = subset || (state().loaded && state().loaded.inputs) || [];
    declared.forEach((param) => {
      const raw = state().fields[paramKey(param.node, param.parameter)];
      if (raw === undefined || raw === "") return;
      let value = raw;
      if (param.type === "GTNumber") {
        value = Number(raw);
        if (Number.isNaN(value)) return;
      }
      if (!inputs[param.node]) inputs[param.node] = {};
      inputs[param.node][param.parameter] = value;
    });
    return inputs;
  }

  // Rejected inputs retain their previous engine values even when the request succeeds.
  function reportRejections(title, result, ranAnyway) {
    const rejected = (result && result.rejected_inputs) || [];
    if (!rejected.length) return false;
    banner(
      "bad",
      rejected.length + " input(s) were rejected. " + title,
      rejected
        .map((entry) => paramKey(entry.node, entry.parameter) + ": " + (entry.reason || "?"))
        .join(" | ") +
        (ranAnyway
          ? ". The run continued with whatever values those parameters already had."
          : ". Everything else was applied."),
    );
    return true;
  }

  async function doSetValues(subset) {
    const reply = await request(VERB.SET_PARAMETER_VALUES, { inputs: collectInputs(subset) });
    setState({ lastSet: reply.result || {} });
    if (!succeeded(reply)) {
      banner("warn", "Nothing was set.", detailOf(reply));
      return;
    }
    const result = reply.result || {};
    if (reportRejections("Applied without running.", result, false)) return;
    if (!subset) {
      banner(
        "info",
        (result.applied_inputs || []).length + " value(s) applied to the loaded graph.",
        "No run started.",
      );
    }
    await doReadValues(["inputs"]);
  }

  // Reads recover values after runs and notification gaps.
  async function doReadValues(sections) {
    const reply = await request(VERB.GET_PARAMETER_VALUES, { sections: sections || [] });
    if (!succeeded(reply)) {
      setState({ pollSummary: "value read failed: " + detailOf(reply) });
      return;
    }
    const result = reply.result || {};
    const read = result.requested_sections || [];
    const patch = {};
    // Preserve sections absent from requested_sections; an empty requested section clears it.
    if (read.indexOf("inputs") !== -1) patch.inputValues = flattenValues(result.inputs, false);
    if (read.indexOf("outputs") !== -1) patch.outputValues = flattenValues(result.outputs, false);
    setState(patch);
  }

  // Coalesce writes and refuse them mid-run because node-read timing is indeterminate.
  const writeTimers = new Map();

  function setField(param, value) {
    const key = paramKey(param.node, param.parameter);
    const fields = Object.assign({}, state().fields, { [key]: value });
    setState({ fields });
    rememberFields((state().loaded || {}).workflow_id, fields);
    if (!state().writeThrough || !state().loaded || state().runActive) return;

    const existing = writeTimers.get(key);
    if (existing) clearTimeout(existing);
    writeTimers.set(
      key,
      setTimeout(() => {
        writeTimers.delete(key);
        guard(() => doSetValues([param]))();
      }, WRITE_THROUGH_DEBOUNCE_MS),
    );
  }

  async function doRun() {
    if (!state().loaded || state().runActive) return;
    setState({
      nodeStates: [],
      execution: null,
      executionNodeSets: [],
      runTotal: null,
      runActive: false,
      viewingRun: null,
      pollTicks: 0,
    });
    noteRunActivity(true);

    // Open logging and polling before execute; its reply arrives after terminal events.
    openRun();
    startPolling();

    // Supplying the loaded id rejects a graph swapped out by another client.
    const reply = await request(
      VERB.EXECUTE_WORKFLOW,
      {
        workflow_id: state().loaded.workflow_id,
        inputs: collectInputs(),
      },
      EXECUTE_TIMEOUT_MS,
    );

    if (!succeeded(reply)) {
      stopPolling();
      discardRun();
      setState({ runActive: false, runStartedAt: null, runOrigin: null });
      banner("bad", "Run refused.", detailOf(reply));
      return;
    }

    if (reportRejections("The run went ahead anyway.", reply.result || {}, true)) return;
    setState({ banner: null });
  }

  async function doCancel() {
    const reply = await request(VERB.CANCEL_EXECUTION, {});
    if (succeeded(reply)) {
      banner("warn", "Cancel accepted.", "Waiting for the terminal notification.");
    } else {
      banner("warn", "Cancel refused.", detailOf(reply));
    }
  }

  let pollTimer = null;

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // Events report progress; polling recovers fire-and-forget events with no replay.
  function startPolling() {
    stopPolling();
    pollTimer = setInterval(() => {
      if (!state().runActive || !isOpen()) {
        stopPolling();
        return;
      }
      guard(doPollTick)();
    }, POLL_TICK_MS);
  }

  async function doPollTick() {
    const [stateReply, valuesReply] = await requestBatch([
      { requestType: VERB.GET_EXECUTION_STATE, payload: {} },
      { requestType: VERB.GET_PARAMETER_VALUES, payload: { sections: ["outputs"] } },
    ]);
    setState({ pollTicks: state().pollTicks + 1 });

    if (succeeded(stateReply)) {
      const result = stateReply.result || {};
      // Poll totals come from declared nodes and do not depend on event delivery.
      const patch = {
        pollSummary:
          "running " +
          result.running +
          ", active " +
          JSON.stringify(result.active_nodes || []) +
          ", involved " +
          (result.involved_nodes || []).length,
      };
      if (!state().runTotal && (result.involved_nodes || []).length) {
        patch.runTotal = result.involved_nodes;
      }
      if (result.running === false && state().runActive) {
        patch.runActive = false;
        patch.runEndedAt = Date.now();
        setTimeout(() => closeRun(null), DRAIN_GRACE_MS);
      }
      setState(patch);
    }
    if (succeeded(valuesReply)) {
      setState({ outputValues: flattenValues((valuesReply.result || {}).outputs, false) });
    }
  }

  // History is connection-local because output paths may be overwritten.

  let runSeq = 0;

  function openRun() {
    const loaded = state().loaded || {};
    runSeq += 1;
    setState({
      history: [
        {
          id: runSeq,
          workflowId: loaded.workflow_id || "",
          workflowName: loaded.name || loaded.workflow_id || "",
          declared: loaded.outputs || [],
          fields: Object.assign({}, state().fields),
          startedAt: Date.now(),
          endedAt: null,
          state: "running",
          outputs: {},
          failures: [],
        },
      ]
        .concat(state().history)
        .slice(0, HISTORY_LIMIT),
    });
  }

  // Remove the provisional entry when execute refuses the run.
  function discardRun() {
    setState({ history: state().history.filter((run) => run.state !== "running") });
  }

  // Node-state events are the only recoverable source of failure details.
  function closeRun(terminal) {
    const history = state().history.slice();
    const entry = history.find((run) => run.state === "running");
    if (!entry) return;
    const failures = state()
      .nodeStates.filter((node) => node.state === "failed")
      .map((node) => ({ node: node.node, detail: node.detail }));
    Object.assign(entry, {
      endedAt: state().runEndedAt || Date.now(),
      state: terminal ? terminal.state || "completed" : "completed",
      outputs: Object.assign({}, state().outputValues),
      failures,
    });
    setState({ history });
    if (failures.length) {
      banner(
        "bad",
        failures.length + " node(s) failed.",
        failures.map((failure) => failure.node + ": " + failure.detail).join(" | "),
      );
    }
  }

  // Terminal events omit outputs, so read them after trailing values arrive.
  function finishRun(terminal) {
    stopPolling();
    if (state().loaded) {
      setTimeout(() => guard(() => doReadValues(["outputs"]))(), DRAIN_GRACE_MS);
    }
    setTimeout(() => closeRun(terminal), DRAIN_GRACE_MS + 250);
  }

  function doRerun(entry) {
    const loaded = state().loaded;
    if (!loaded || loaded.workflow_id !== entry.workflowId) return;
    setState({ fields: Object.assign({}, entry.fields), viewingRun: null });
    rememberFields(entry.workflowId, entry.fields);
    guard(doRun)();
  }

  // Workflow registration follows the current project's workspace.

  async function doListProjects() {
    const reply = await request(VERB.LIST_PROJECTS, {
      include_system_builtins: state().includeSystemBuiltins,
    });
    if (!succeeded(reply)) {
      setState({ projectNote: "listing failed: " + detailOf(reply) });
      return;
    }
    setState({ projects: (reply.result && reply.result.projects) || [], projectNote: "" });
  }

  async function doReadCurrentProject() {
    const reply = await request(VERB.GET_CURRENT_PROJECT, {});
    if (!succeeded(reply)) {
      // No current project differs from the system-default project.
      setState({ currentProject: null, projectNote: "no current project: " + detailOf(reply) });
      return;
    }
    setState({ currentProject: reply.result || {}, projectNote: "" });
  }

  async function doDescribeProject(projectId) {
    setState({ projectChoice: projectId });
    if (!projectId) {
      setState({ describedProject: null });
      return;
    }
    const reply = await request(VERB.DESCRIBE_PROJECT, { project_id: projectId });
    if (!succeeded(reply)) {
      setState({ describedProject: null, projectNote: "describe failed: " + detailOf(reply) });
      return;
    }
    setState({ describedProject: reply.result || {}, projectNote: "" });
  }

  // Switching may reload this library and tear down its request and event handlers.
  async function doSetProject(projectId) {
    const target =
      projectId === null
        ? "the system defaults"
        : (state().projects.find((project) => project.id === projectId) || {}).name || projectId;
    const proceed = window.confirm(
      "Switch to " +
        target +
        "?\n\nThe engine may re-register every workflow and reload every library, this one included. " +
        "This panel reconnects afterwards and drops every id it cached.",
    );
    if (!proceed) return;

    const reply = await request(VERB.SET_CURRENT_PROJECT, { project_id: projectId });
    if (!succeeded(reply)) {
      banner("warn", "Project switch refused.", detailOf(reply));
      return;
    }
    setState({
      workflows: [],
      described: null,
      loaded: null,
      fields: {},
      inputValues: {},
      outputValues: {},
      describedProject: null,
      projectChoice: "",
      history: [],
      viewingRun: null,
    });
    banner(
      "warn",
      "Switched to " + target + ". Reconnecting.",
      "workspace_changed " + (reply.result || {}).workspace_changed + ".",
    );
    setState({ autoConnect: true, connectAttempts: 0 });
    closeSocket(4002, "project switch");
  }

  return {
    seedFields,
    doList,
    doDescribe,
    doLoad,
    collectInputs,
    doSetValues,
    doReadValues,
    setField,
    doRun,
    doCancel,
    stopPolling,
    startPolling,
    doPollTick,
    finishRun,
    doRerun,
    doListProjects,
    doReadCurrentProject,
    doDescribeProject,
    doSetProject,
  };
})();
