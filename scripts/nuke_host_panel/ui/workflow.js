// A menu, not a browser: no ids on screen. Picking describes, which changes nothing. Loading is a
// second press, because it clears the engine.
(function () {
  const { guard, setState } = Store;
  const { doDescribe, doLoad } = Actions;
  const { html } = Ui;

  function WorkflowPane({ st }) {
    const runnable = st.workflows.filter((workflow) => workflow.runnable);
    const blocked = st.workflows.filter((workflow) => !workflow.runnable);
    const described = st.described;
    const loadedId = (st.loaded && st.loaded.workflow_id) || "";
    const isLoaded = described && described.workflow_id === loadedId;

    return html`
      <div class="pane">
        <h2>Workflow<span class="right muted">${runnable.length} runnable</span></h2>
        <div class="body">
          <div class="field">
            <label>workflow</label>
            <select
              disabled=${!st.session || st.runActive}
              value=${(described && described.workflow_id) || ""}
              onChange=${(e) => {
                if (!e.target.value) return;
                guard(() => doDescribe(e.target.value))();
              }}
            >
              <option value="">${runnable.length ? "pick a workflow" : "none available"}</option>
              ${runnable.map(
                (workflow) => html`
                  <option value=${workflow.id}>${workflow.name || workflow.id}</option>
                `,
              )}
            </select>
            <span></span>
          </div>

          ${
            !st.session
              ? html`<div class="empty">Waiting for an engine.</div>`
              : !described
                ? html`<div class="empty">Picking one describes it. Nothing is loaded.</div>`
                : html`
                    ${
                      described.description
                        ? html`<div class="muted">${described.description}</div>`
                        : null
                    }
                    <div class="stack">
                      <span class="muted">
                        ${
                          (described.inputs || []).length +
                          " input(s), " +
                          (described.outputs || []).length +
                          " output(s)"
                        }
                      </span>
                      ${isLoaded ? html`<span class="badge warn">LOADED</span>` : null}
                    </div>
                    ${
                      isLoaded
                        ? null
                        : html`
                            <div class="stack">
                              <button
                                class="primary"
                                disabled=${st.runActive}
                                onClick=${guard(() => doLoad({ workflow_id: described.workflow_id }))}
                              >
                                Load into the engine
                              </button>
                              <span class="muted">
                                ${
                                loadedId
                                  ? "Discards " + ((st.loaded && st.loaded.name) || loadedId) + "."
                                  : "Clears all engine object state."
                              }
                              </span>
                            </div>
                          `
                    }
                  `
          }

          <div class="split">
            <div class="stack">
              <input
                class="grow"
                type="text"
                placeholder="/path/to/workflow.py"
                disabled=${st.runActive}
                value=${st.loadFilePath}
                onInput=${(e) => setState({ loadFilePath: e.target.value })}
              />
              <button
                disabled=${!st.session || st.runActive || !st.loadFilePath.trim()}
                onClick=${guard(() => doLoad({ file_path: st.loadFilePath.trim() }))}
              >
                Load file
              </button>
            </div>
            <div class="muted">
              A file is imported and registered first, and the reply names the id it resolved to.
              One selector or the other, never both.
            </div>
          </div>

          ${
            blocked.length
              ? html`<div class="split">
                  <div class="sub">not offered</div>
                  <!-- Reported rather than hidden: an absence carries no reason. -->
                  ${blocked.map(
                    (workflow) => html`
                      <div class="stale">
                        <div class="stack">
                          <span class="clip grow">${workflow.name || workflow.id}</span>
                          <span class="badge bad">unavailable</span>
                        </div>
                        <div class="muted">${workflow.unavailable_reason || ""}</div>
                      </div>
                    `,
                  )}
                </div>`
              : null
          }
        </div>
      </div>
    `;
  }

  Panes.WorkflowPane = WorkflowPane;
})();
