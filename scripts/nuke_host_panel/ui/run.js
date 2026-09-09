// Resolved node states over the run's node set. The ratio can top out below 1.0 on a clean run: the
// total counts what a flow declares, and an untaken branch never resolves.
(function () {
  const { EXECUTION_STATES, KNOWN_NODE_STATES } = Protocol;
  const { html, stateClass } = Ui;

  function RunPane({ st }) {
    const resolved = st.nodeStates.filter((entry) => entry.state === "resolved").length;
    const failed = st.nodeStates.filter((entry) => entry.state === "failed");
    const denominator = st.runTotal ? st.runTotal.length : 0;
    const ratio = denominator ? Math.min(resolved / denominator, 1) : 0;
    const subflows = st.executionNodeSets.filter((set) => set.length > 0).length - 1;
    const now = Date.now();
    const elapsed = !st.runStartedAt
      ? null
      : (((st.runActive ? now : st.runEndedAt || now) - st.runStartedAt) / 1000).toFixed(1);

    return html`
      <div class="pane">
        <h2>
          Run
          <span class="right">
            ${
              st.runActive
                ? html`<span class="chip running">running</span>`
                : st.execution
                  ? html`<span class=${"chip " + stateClass(st.execution.state, EXECUTION_STATES)}>
                      ${st.execution.state || "?"}
                    </span>`
                  : html`<span class="muted">idle</span>`
            }
          </span>
        </h2>
        <div class="body">
          ${
            !st.runStartedAt && !st.execution
              ? html`<div class="empty">Nothing has run on this connection.</div>`
              : html`
                  <div class="stack">
                    <span class="muted">
                      ${
                        denominator
                          ? resolved + " / " + denominator + " nodes"
                          : resolved + " / ? nodes"
                      }
                    </span>
                    ${elapsed ? html`<span class="muted">${elapsed}s</span>` : null}
                    ${
                      st.runOrigin === "elsewhere"
                        ? html`<span class="badge warn">STARTED ELSEWHERE</span>`
                        : null
                    }
                    ${subflows > 0 ? html`<span class="badge">${subflows} subflow(s)</span>` : null}
                    <span class="grow"></span>
                    ${
                      st.runActive && st.pollTicks
                        ? html`<span class="muted" title=${st.pollSummary}>
                            ${st.pollTicks} backstop poll(s)
                          </span>`
                        : null
                    }
                  </div>
                  <div class="bar">
                    <div
                      class=${"fill" + (denominator ? "" : " unknown")}
                      style=${"width: " + (denominator ? (ratio * 100).toFixed(1) : 100) + "%"}
                    ></div>
                  </div>
                  ${
                    !denominator && st.runActive
                      ? html`<div class="muted">
                          No total yet. A flow whose start node is also its end node emits none.
                        </div>`
                      : null
                  }
                  <div class="nodes">
                    ${st.nodeStates.map(
                      (entry) => html`
                        <span class="n" title=${entry.detail || entry.state}>
                          <span class=${"sw " + stateClass(entry.state, KNOWN_NODE_STATES)}></span>
                          ${entry.node}
                        </span>
                      `,
                    )}
                  </div>
                  ${
                    failed.length
                      ? html`<div class="split">
                          ${failed.map(
                          (entry) => html`
                            <div class="stack">
                              <span class="chip failed">failed</span>
                              <span>${entry.node}</span>
                            </div>
                            <div class="muted">${entry.detail || "no detail reported"}</div>
                          `,
                        )}
                          <p class="note">
                            The terminal event reports <code>completed</code> either way: it fires
                            on a clean run and an errored one and carries no outcome. A live node
                            state event is the only place a failure appears.
                          </p>
                        </div>`
                      : null
                  }
                  ${
                    st.execution && st.execution.detail
                      ? html`<div class="muted">${st.execution.detail}</div>`
                      : null
                  }
                `
          }
        </div>
      </div>
    `;
  }

  Panes.RunPane = RunPane;
})();
