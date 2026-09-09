// Everything the panel asks the engine to do, plus the run log it keeps for itself.
//
// One module per concern would be smaller files and more of them; these all read and write the same
// loaded-workflow state, so they live together and are grouped by section below.
const Actions = (function () {
  const { VERB } = Protocol;
  const { DRAIN_GRACE_MS, HISTORY_LIMIT, POLL_TICK_MS, WRITE_THROUGH_DEBOUNCE_MS } = Config;
  const { banner, guard, remembered, rememberFields, remember, setState, state } = Store;
  const { closeSocket, detailOf, isOpen, request, requestBatch, succeeded } = Transport;
  const { noteRunActivity } = Events;
  const { fieldValueFrom, flattenValues, paramKey } = Values;

  /* ---------------------------------------------------------------- input seeding */

  // Seed from input_values, the graph's current values, not from a descriptor's default, which is the
  // workflow author's value. Where the graph reports nothing, the last local value beats an empty
  // field: a scalar descriptor carries its type and not its value, so the engine cannot report one
  // back even when it holds it.
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

  /* -------------------------------------------------------------------- workflows */

  async function doList() {
    // runnable_only false on purpose: the unavailable entries carry the reason, and an absence does
    // not.
    const reply = await request(VERB.LIST_WORKFLOWS, { runnable_only: false });
    if (!succeeded(reply)) {
      banner("bad", "Listing workflows failed.", detailOf(reply));
      return;
    }
    setState({ workflows: (reply.result && reply.result.workflows) || [] });
  }

  // Reads the registry and changes nothing, so this is safe on selection: show what a workflow
  // declares before committing to the destructive load.
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

  // The only verb that changes what is loaded, and required before execute, the value verbs, or
  // execution state can answer for the workflow a host means. Destructive: the engine clears all
  // object state, including a graph opened elsewhere on the same engine.
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
      // Branch on engine_state_cleared, never on the reason text. False means the values on screen
      // still match what the engine holds and a retry is free.
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
          .join(" | ") + ". Reported rather than omitted: unset and unreadable differ.",
      );
    }
  }

  /* ----------------------------------------------------------------------- values */

  // Addressed as {node: {parameter: value}}, using the node and parameter the declaration reported.
  // A subset is passed when writing through a single edit.
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

  // A rejection is not a failure of the request, and it is the worst failure mode here: the engine
  // keeps the value it already had, so the run produces plausible output computed from an input
  // nobody set.
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

  // The recovery path for values: read after a run, and after a reconnect that missed every
  // notification. Loaded-state-addressed, so it names no workflow.
  async function doReadValues(sections) {
    const reply = await request(VERB.GET_PARAMETER_VALUES, { sections: sections || [] });
    if (!succeeded(reply)) {
      setState({ pollSummary: "value read failed: " + detailOf(reply) });
      return;
    }
    const result = reply.result || {};
    const read = result.requested_sections || [];
    const patch = {};
    // requested_sections tells "not asked for" from "asked for, got nothing", so a section that was
    // not read keeps whatever was on screen.
    if (read.indexOf("inputs") !== -1) patch.inputValues = flattenValues(result.inputs, false);
    if (read.indexOf("outputs") !== -1) patch.outputValues = flattenValues(result.outputs, false);
    setState(patch);
  }

  // An edit that only lives in the panel is an edit the engine does not have, so writes go through,
  // coalesced. Refused mid-run by design: the scheduler decides when a node reads a parameter, so a
  // value set during a run cannot be told apart from one that landed late.
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

  /* -------------------------------------------------------------------- execution */

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

    // Sending the loaded id turns a graph swapped out from under this panel into a refusal instead
    // of a run of the wrong thing.
    const reply = await request(VERB.EXECUTE_WORKFLOW, {
      workflow_id: state().loaded.workflow_id,
      inputs: collectInputs(),
    });

    if (!succeeded(reply)) {
      setState({ runActive: false, runStartedAt: null, runOrigin: null });
      banner("bad", "Run refused.", detailOf(reply));
      return;
    }

    openRun();
    startPolling();

    if (reportRejections("The run started anyway.", reply.result || {}, true)) return;
    setState({ banner: null });
  }

  async function doCancel() {
    const reply = await request(VERB.CANCEL_EXECUTION, {});
    if (succeeded(reply)) {
      // Not confirmation that execution stopped: the terminal state arrives as a notification.
      banner("warn", "Cancel accepted.", "Waiting for the terminal notification.");
    } else {
      banner("warn", "Cancel refused.", detailOf(reply));
    }
  }

  /* ------------------------------------------------------------- backstop polling */

  let pollTimer = null;

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // Not the progress mechanism: the events are. This is the backstop for delivery that is fire and
  // forget with no replay, and it reads two verbs in one frame.
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
      // involved_nodes here is derived from the flow's declared nodes rather than from event
      // history, so it does not depend on which events arrived.
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
        // A terminal event that never arrived would otherwise leave the panel locked.
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

  /* ----------------------------------------------------------------- the run log */
  //
  // In memory for this connection only: a run's outputs point at files, and a remembered path is a
  // path something else may have overwritten.

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

  // Failures are copied off the node states: the terminal event carries no outcome, and no later
  // read recovers one.
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

  // Registered as the terminal-event hook. Outputs are not on the terminal event and never will be,
  // so they are read here, which is the same call a reconnect makes. One code path.
  function finishRun(terminal) {
    stopPolling();
    if (state().loaded) {
      setTimeout(() => guard(() => doReadValues(["outputs"]))(), DRAIN_GRACE_MS);
    }
    setTimeout(() => closeRun(terminal), DRAIN_GRACE_MS + 250);
  }

  // Not a protocol feature. It restores the values a past run used, then takes the ordinary run path.
  function doRerun(entry) {
    const loaded = state().loaded;
    if (!loaded || loaded.workflow_id !== entry.workflowId) return;
    setState({ fields: Object.assign({}, entry.fields), viewingRun: null });
    rememberFields(entry.workflowId, entry.fields);
    guard(doRun)();
  }

  /* --------------------------------------------------------------------- projects */
  //
  // Workflows are registered per workspace and a project decides the workspace, so the workflow list
  // is a list for whichever project the engine is on.

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
      // A failure means no current project at all, which the engine treats as different from being
      // on the system defaults.
      setState({ currentProject: null, projectNote: "no current project: " + detailOf(reply) });
      return;
    }
    setState({ currentProject: reply.result || {}, projectNote: "" });
  }

  // Reads a project's workspace and validation without activating it.
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

  // Can re-register every workflow and reload every library, this one included, which tears down the
  // handlers answering this request and the bridge pushing its events.
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
      "workspace_changed " +
        (reply.result || {}).workspace_changed +
        ". Reconnecting either way: the engine reloads libraries on a decision it reports no field " +
        "for, and a reload stops every notification without an error.",
    );
    // Reconnect rather than disconnect: the resync sequence re-reads the project, the workflow list,
    // and whatever is loaded.
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
