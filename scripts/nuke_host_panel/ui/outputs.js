(function () {
  const { useState } = preactHooks;
  const { EXECUTION_STATES, PREVIEWABLE, isMedia, isScalar } = Protocol;
  const { setState } = Store;
  const { doRerun } = Actions;
  const { nukeNodePlan, paramKey, valueItems } = Values;
  const { clock, copyButton, html, stateClass } = Ui;

  // Browsers load local files only from pages opened from disk.
  function fileUrl(path) {
    if (!path) return null;
    const slashed = String(path).replace(/\\/g, "/");
    const absolute = slashed.charAt(0) === "/" ? slashed : "/" + slashed;
    return "file://" + encodeURI(absolute).replace(/#/g, "%23");
  }

  function Preview({ valueType, url, local }) {
    const [failed, setFailed] = useState(false);
    const tag = PREVIEWABLE[valueType];
    if (!tag || !url) return null;
    if (failed) {
      return html`<div class="muted">
        ${
          local
            ? "Preview failed. A browser loads a local file only from a local page, so this needs " +
              "index.html opened from disk rather than served."
            : "Preview failed. The engine can reach this URL; this browser cannot."
        }
      </div>`;
    }
    if (tag === "video") {
      return html`<video src=${url} controls onError=${() => setFailed(true)}></video>`;
    }
    return html`<img src=${url} onError=${() => setFailed(true)} />`;
  }

  function Entry({ valueType, entry }) {
    if (!entry || !entry.path) return html`<div class="src muted">Unset item.</div>`;
    const padded = /#+/.test(entry.path);
    return html`
      <div class="src">
        <div class="stack">
          <span class="muted">${entry.format || "format unknown"}</span>
          ${padded ? html`<span class="badge warn">#### PATTERN</span>` : null}
        </div>
        <div class="stack">
          <span class="mono grow">${entry.path}</span>
          ${copyButton(entry.path)}
        </div>
        ${
          padded
            ? html`<div class="muted">Frame padding: valid for a file knob, invalid for an open().</div>`
            : html`<${Preview} valueType=${valueType} url=${fileUrl(entry.path)} local />`
        }
      </div>
    `;
  }

  function OutputCard({ param, entry }) {
    const descriptor = (entry && entry.value) || null;
    const valueType = descriptor ? descriptor.value_type || "?" : null;
    const items = valueItems(descriptor);
    const scalar = valueType && isScalar(valueType);

    return html`
      <div class="out">
        <div class="top">
          <span class="clip grow" title=${paramKey(param.node, param.parameter)}
            >${param.name || paramKey(param.node, param.parameter)}</span
          >
          ${
            valueType
              ? html`<span class=${"badge" + (scalar ? "" : " good")}>${valueType}</span>`
              : html`<span class="badge">declares ${param.type || "?"}</span>`
          }
          ${
            descriptor && Array.isArray(descriptor.value) && descriptor.value.length > 1
              ? html`<span class="badge warn">${descriptor.value.length} ITEMS</span>`
              : null
          }
          ${entry && entry.live ? html`<span class="badge">pushed</span>` : null}
        </div>
        <div class="inner">
          ${
            !descriptor
              ? html`<div class="empty">No value yet.</div>`
              : html`
                  ${
                    !items.length
                      ? html`<div class="flat muted">Unset.</div>`
                      : scalar
                        ? html`<div class="flat mono">
                            ${
                              items.length === 1 && items[0] === ""
                                ? html`<span class="muted">Empty.</span>`
                                : items.map(String).join(", ")
                            }
                          </div>`
                        : items.map((item) => html`<${Entry} valueType=${valueType} entry=${item} />`)
                  }
                  ${
                    isMedia(valueType)
                      ? html`<details class="plan">
                          <summary>as a Nuke node</summary>
                          ${nukeNodePlan(descriptor).map(
                          (step) => html`
                            <div>
                              ${step.call ? html`<div class="call">${step.call}</div>` : null}
                              <div class="muted">${step.note}</div>
                              ${step.call && step.source ? copyButton(step.source, "copy path") : null}
                            </div>
                          `,
                        )}
                          <div class="diag">engine_type ${descriptor.engine_type || "?"}, diagnostic only.</div>
                        </details>`
                      : null
                  }
                `
          }
        </div>
      </div>
    `;
  }

  function OutputsPane({ st }) {
    const viewing = st.viewingRun
      ? st.history.find((run) => run.id === st.viewingRun) || null
      : null;
    const declared = viewing ? viewing.declared : (st.loaded && st.loaded.outputs) || [];
    const values = viewing ? viewing.outputs : st.outputValues;

    return html`
      <div class="pane fill">
        <h2>Outputs<span class="right muted">${declared.length || "-"} declared</span></h2>
        <div class="body">
          ${
            viewing
              ? html`<div class="stack">
                  <span class="badge warn">EARLIER RUN</span>
                  <span class="muted grow">${clock(viewing.startedAt)}</span>
                  <button class="tiny" onClick=${() => setState({ viewingRun: null })}>
                    back to latest
                  </button>
                </div>`
              : null
          }
          ${
            !declared.length
              ? html`<div class="empty">Load a workflow to see what it produces.</div>`
              : declared.map(
                  (param) => html`
                    <${OutputCard}
                      param=${param}
                      entry=${values[paramKey(param.node, param.parameter)]}
                    />
                  `,
                )
          }
        </div>
      </div>
    `;
  }

  function HistoryPane({ st }) {
    const loadedId = (st.loaded && st.loaded.workflow_id) || "";
    return html`
      <div class="pane">
        <h2>History<span class="right muted">this connection</span></h2>
        <div class="body">
          ${
            !st.history.length
              ? html`<div class="empty">No runs yet.</div>`
              : st.history.map(
                  (run) => html`
                    <div
                      class=${"item pick" + (st.viewingRun === run.id ? " sel" : "")}
                      onClick=${() =>
                        setState({ viewingRun: st.viewingRun === run.id ? null : run.id })}
                    >
                      <span class="when">${clock(run.startedAt)}</span>
                      <span class=${"chip " + stateClass(run.state, EXECUTION_STATES)}
                        >${run.state}</span
                      >
                      <span class="clip grow">${run.workflowName}</span>
                      ${
                        run.failures && run.failures.length
                          ? html`<span class="badge bad">${run.failures.length} failed</span>`
                          : null
                      }
                      ${
                        run.endedAt
                          ? html`<span class="muted">
                              ${((run.endedAt - run.startedAt) / 1000).toFixed(1)}s
                            </span>`
                          : null
                      }
                      <button
                        class="tiny"
                        disabled=${st.runActive || run.workflowId !== loadedId}
                        title=${
                          run.workflowId === loadedId
                            ? "Restore this run's values and run again"
                            : "That workflow is not loaded"
                        }
                        onClick=${(e) => {
                          e.stopPropagation();
                          doRerun(run);
                        }}
                      >
                        re-run
                      </button>
                    </div>
                  `,
                )
          }
        </div>
      </div>
    `;
  }

  Panes.OutputsPane = OutputsPane;
  Panes.HistoryPane = HistoryPane;
})();
