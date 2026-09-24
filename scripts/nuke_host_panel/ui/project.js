(function () {
  const { usableProject } = Protocol;
  const { guard, persist, setState } = Store;
  const { doDescribeProject, doListProjects, doSetProject } = Actions;
  const { html } = Ui;

  function ProjectPane({ st }) {
    const current = st.currentProject;
    const described = st.describedProject;
    const chosen = st.projects.find((project) => project.id === st.projectChoice);
    const listedCurrent = st.projects.find((project) => project.current);
    // Show the current project until the user picks one to preview.
    const shown = st.projectChoice || (listedCurrent ? listedCurrent.id : "");
    const switchable = chosen && chosen.available && !chosen.current && !st.runActive;

    return html`
      <div class="pane">
        <h2>Project<span class="right muted">${st.projects.length || "-"} loaded</span></h2>
        <div class="body">
          ${
            !current
              ? html`<div class="empty">
                  ${st.session ? "No current project set." : "Waiting for an engine."}
                </div>`
              : html`
                  <div class="stack">
                    <b class="clip grow">${current.name || "(no name reported)"}</b>
                    <span
                      class=${"badge " + (usableProject(current.validation_status) ? "good" : "bad")}
                    >
                      ${current.validation_status || "?"}
                    </span>
                  </div>
                  <div class="mono muted">${current.workspace_dir || ""}</div>
                  ${
                    (current.problems || []).length
                      ? html`<div class="muted">${(current.problems || []).join(" | ")}</div>`
                      : null
                  }
                `
          }

          <div class="field">
            <label>switch to</label>
            <select
              disabled=${!st.session || st.runActive}
              value=${shown}
              onChange=${(e) => guard(() => doDescribeProject(e.target.value))()}
            >
              <option value="">${st.projects.length ? "preview a project" : "none listed"}</option>
              ${st.projects.map(
                (project) => html`
                  <option value=${project.id} disabled=${!project.available}>
                    ${
                      (project.name || "(no name reported)") +
                      (project.current ? "  (current)" : "") +
                      (project.available ? "" : "  unavailable")
                    }
                  </option>
                `,
              )}
            </select>
            <span></span>
          </div>

          ${
            chosen && !chosen.available
              ? html`<div class="muted">${chosen.unavailable_reason || "Unavailable."}</div>`
              : null
          }
          ${
            described
              ? html`
                  <div class="split">
                    <table>
                      <tbody>
                        <tr>
                          <th>workspace_dir</th>
                          <td class="mono">
                            ${described.workspace_dir || "(no readable project file)"}
                          </td>
                        </tr>
                        <tr>
                          <th>validation</th>
                          <td>
                            <span
                              class=${
                                "badge " +
                                (usableProject(described.validation_status) ? "good" : "bad")
                              }
                            >
                              ${described.validation_status || "?"}
                            </span>
                            ${(described.problems || []).join(" | ")}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                    <div class="stack">
                      <button
                        disabled=${!switchable}
                        onClick=${guard(() => doSetProject(st.projectChoice))}
                      >
                        Switch and reconnect
                      </button>
                    </div>
                  </div>
                `
              : null
          }

          <div class="stack">
            <label>
              <input
                type="checkbox"
                checked=${st.includeSystemBuiltins}
                onChange=${(e) => {
                  setState({ includeSystemBuiltins: e.target.checked });
                  persist();
                  if (st.session) guard(doListProjects)();
                }}
              />
              system defaults
            </label>
            <button class="tiny" disabled=${!st.session} onClick=${guard(doListProjects)}>
              refresh
            </button>
            <button
              class="tiny"
              disabled=${!st.session || st.runActive}
              title="project_id null asks for the system defaults"
              onClick=${guard(() => doSetProject(null))}
            >
              use system defaults
            </button>
          </div>
          ${st.projectNote ? html`<div class="muted">${st.projectNote}</div>` : null}
        </div>
      </div>
    `;
  }

  Panes.ProjectPane = ProjectPane;
})();
