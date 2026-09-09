// One row per declared input, widget chosen from its host type. That is the point of the
// declaration: the panel is generated, not written per workflow.
(function () {
  const { KNOWN_VALUE_TYPES, isMedia } = Protocol;
  const { guard, persist, setState } = Store;
  const { doCancel, doReadValues, doRun, doSetValues, setField } = Actions;
  const { paramKey } = Values;
  const { html } = Ui;

  function Field({ param, value, locked }) {
    const key = paramKey(param.node, param.parameter);
    const set = (v) => setField(param, v);
    // settable false means the engine will refuse a value for this parameter, ever. locked means a
    // run is in flight.
    const readOnly = param.settable === false;
    const disabled = readOnly || locked;

    let widget;
    if (param.type === "GTBool") {
      widget = html`<input
        type="checkbox"
        disabled=${disabled}
        checked=${value === true}
        onChange=${(e) => set(e.target.checked)}
      />`;
    } else if (param.type === "GTNumber") {
      widget = html`<input
        type="number"
        step="any"
        disabled=${disabled}
        value=${value === undefined ? "" : value}
        onInput=${(e) => set(e.target.value)}
      />`;
    } else if (param.type === "GTNull") {
      widget = html`<input type="text" disabled placeholder="GTNull, nothing to send" />`;
    } else {
      widget = html`<input
        type="text"
        disabled=${disabled}
        placeholder=${isMedia(param.type) ? "/path/to/file.####.exr" : ""}
        value=${value === undefined ? "" : value}
        onInput=${(e) => set(e.target.value)}
      />`;
    }

    return html`
      <div class="field">
        <label title=${param.tooltip || key}>${param.name || key}</label>
        <div>${widget}</div>
        <span class="type">
          ${param.type || "?"}${readOnly ? " ro" : ""}
          ${KNOWN_VALUE_TYPES.indexOf(param.type) === -1 ? " unknown" : ""}
        </span>
      </div>
    `;
  }

  function ParametersPane({ st }) {
    const loaded = st.loaded;
    const declared = (loaded && loaded.inputs) || [];

    return html`
      <div class="pane">
        <h2>
          Parameters
          <span class="right muted clip"
            >${loaded ? loaded.name || "(unnamed)" : "nothing loaded"}</span
          >
        </h2>
        <div class="body">
          ${
            !loaded
              ? html`<div class="empty">Load a workflow to build its parameters.</div>`
              : html`
                  ${
                    !declared.length
                      ? html`<div class="empty">This workflow declares no inputs.</div>`
                      : declared.map(
                          (param) => html`
                            <${Field}
                              param=${param}
                              locked=${st.runActive}
                              value=${st.fields[paramKey(param.node, param.parameter)]}
                            />
                          `,
                        )
                  }

                  <div class="stack">
                    <!-- One button, because there is one execution at a time. -->
                    ${
                      st.runActive
                        ? html`<button class="danger" onClick=${guard(doCancel)}>Cancel</button>`
                        : html`<button
                            class="primary"
                            disabled=${!st.session}
                            onClick=${guard(doRun)}
                          >
                            Run
                          </button>`
                    }
                    <label title="Write each edit through to the engine, coalesced">
                      <input
                        type="checkbox"
                        checked=${st.writeThrough}
                        onChange=${(e) => {
                          setState({ writeThrough: e.target.checked });
                          persist();
                        }}
                      />
                      write through
                    </label>
                    ${
                      st.writeThrough
                        ? null
                        : html`<button
                            disabled=${st.runActive}
                            onClick=${guard(() => doSetValues())}
                          >
                            Apply
                          </button>`
                    }
                    <span class="grow"></span>
                    <button
                      class="tiny"
                      disabled=${st.runActive}
                      title="Re-read what the engine holds for these parameters"
                      onClick=${guard(() => doReadValues(["inputs"]))}
                    >
                      re-read
                    </button>
                  </div>

                  ${
                    st.runActive
                      ? html`<div class="muted">
                          Locked during a run: the scheduler decides when a node reads a parameter,
                          so a value set now cannot be told apart from one that landed late.
                        </div>`
                      : null
                  }
                  ${
                    st.restored
                      ? html`<div class="muted">
                          ${
                          st.restored +
                          " value(s) came from local memory: a scalar descriptor carries the type and not " +
                          "the value, so the engine cannot report those back."
                        }
                        </div>`
                      : null
                  }
                  ${
                    st.lastSet
                      ? html`<div class="muted">
                          ${
                          "last write: " +
                          (st.lastSet.applied_inputs || []).length +
                          " applied, " +
                          (st.lastSet.rejected_inputs || []).length +
                          " rejected"
                        }
                        </div>`
                      : null
                  }
                `
          }
        </div>
      </div>
    `;
  }

  Panes.ParametersPane = ParametersPane;
})();
