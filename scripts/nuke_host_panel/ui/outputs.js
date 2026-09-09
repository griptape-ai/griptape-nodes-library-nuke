(function () {
  const { useState } = preactHooks;
  const { EXECUTION_STATES, PREVIEWABLE, isMedia, isScalar } = Protocol;
  const { setState } = Store;
  const { doRerun } = Actions;
  const { nukeNodePlan, paramKey } = Values;
  const { clock, copyButton, html, stateClass } = Ui;

  function Preview({ valueType, url }) {
    const [failed, setFailed] = useState(false);
    const tag = PREVIEWABLE[valueType];
    if (!tag || !url) return null;
    // A URL the engine can reach is not necessarily one this browser can reach.
    if (failed) {
      return html`<div class="muted">
        Preview failed. The engine can reach this URL; this browser cannot.
      </div>`;
    }
    if (tag === "video") {
      return html`<video src=${url} controls onError=${() => setFailed(true)}></video>`;
    }
    return html`<img src=${url} onError=${() => setFailed(true)} />`;
  }

  function Source({ valueType, source }) {
    const kind = source.kind || "?";
    return html`
      <div class="src">
        <div class="stack">
          <span class="badge">${kind}</span>
          <!-- format is reported only when known, never guessed. -->
          <span class="muted">${source.format || "format unknown"}</span>
          ${
            source.width && source.height
              ? html`<span class="muted">${source.width}x${source.height}</span>`
              : null
          }
          ${source.byte_count ? html`<span class="muted">${source.byte_count} B</span>` : null}
          ${source.is_pattern ? html`<span class="badge warn">#### PATTERN</span>` : null}
        </div>

        ${
          kind === "url"
            ? html`
                <div class="stack">
                  <a class="mono grow" href=${source.value || "#"} target="_blank" rel="noreferrer">
                    ${source.value || ""}
                  </a>
                  ${copyButton(source.value)}
                </div>
                ${
                  source.is_pattern
                    ? null
                    : html`<${Preview} valueType=${valueType} url=${source.value} />`
                }
              `
            : null
        }
        ${
          kind === "path"
            ? html`
                <div class="stack">
                  <span class="mono grow">${source.value || ""}</span>
                  ${copyButton(source.value)}
                </div>
                ${
                  source.is_pattern
                    ? html`<div class="muted">
                        Frame padding: valid for a file knob, invalid for an open().
                      </div>`
                    : null
                }
              `
            : null
        }
        ${
          kind === "inline"
            ? html`<div class="muted">
                Bytes stayed in the engine. Read the same value in its url or path form, or treat it
                as unavailable.
              </div>`
            : null
        }
        ${
          kind === "macro"
            ? html`
                <!-- Not a path. Opening it turns a config error into a mysterious file error. -->
                <div class="stack">
                  <span class="badge bad">UNRESOLVED</span>
                  <span class="mono">${source.value || source.raw || ""}</span>
                </div>
                <div class="muted">
                  A template that never resolved, usually a workflow variable. A configuration
                  error, not a file.
                </div>
              `
            : null
        }
        ${
          ["url", "path", "inline", "macro"].indexOf(kind) === -1
            ? html`<div class="muted">
                Unrecognized source kind, left alone: ${JSON.stringify(source.value)}
              </div>`
            : null
        }
        ${
          source.raw && source.raw !== source.value
            ? html`<div class="diag">raw: ${source.raw}</div>`
            : null
        }
      </div>
    `;
  }

  function OutputCard({ param, entry }) {
    const descriptor = (entry && entry.value) || null;
    const valueType = descriptor ? descriptor.value_type || "?" : null;
    const sources = descriptor && Array.isArray(descriptor.sources) ? descriptor.sources : [];
    const scalar = valueType && isScalar(valueType);

    return html`
      <div class="out">
        <div class="top">
          <span class="clip grow">${param.name || paramKey(param.node, param.parameter)}</span>
          ${
            valueType
              ? html`<span class=${"badge" + (scalar ? "" : " good")}>${valueType}</span>`
              : html`<span class="badge">declares ${param.type || "?"}</span>`
          }
          ${
            valueType === "GTImage" && sources.length > 1
              ? html`<span class="badge warn">${sources.length} SOURCES</span>`
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
                    scalar
                      ? html`<div class="flat muted">
                          ${
                          valueType === "GTNull"
                            ? "Unset."
                            : "The descriptor carries the type, not the value."
                        }
                        </div>`
                      : null
                  }
                  ${
                    !scalar && !sources.length
                      ? html`<div class="flat muted">
                          No sources, which should not happen: a value pointing at no bytes is
                          reported as GTText.
                        </div>`
                      : null
                  }
                  ${sources.map(
                    (source) => html`<${Source} valueType=${valueType} source=${source || {}} />`,
                  )}
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
                          <div class="diag">
                            engine_type ${descriptor.engine_type || "?"}, diagnostic only.
                            colorspace ${descriptor.colorspace || "null in v1"}
                          </div>
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
          ${
            declared.length
              ? html`<p class="note">
                  Outputs are the end-flow parameters the workflow declared, not whichever node
                  control flow finished on. No terminal event carries them, so
                  <code>NukeGetParameterValuesRequest</code> is what reads them.
                </p>`
              : null
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
