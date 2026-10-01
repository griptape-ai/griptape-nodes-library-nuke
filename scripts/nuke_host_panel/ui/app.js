(function () {
  const { useEffect } = preactHooks;
  const { guard, persist, setState, state } = Store;
  const { doConnect } = Session;
  const { html, useStore } = Ui;
  const { ProjectPane, WorkflowPane, ParametersPane, RunPane, HistoryPane, OutputsPane, Drawer } =
    Panes;

  function Header({ st }) {
    const session = st.session || {};
    const dot = st.session
      ? "on"
      : st.socket === "connecting" || st.socket === "open"
        ? "busy"
        : st.socket.indexOf("disconnected") === 0
          ? "off"
          : "bad";
    const open = (tab) => {
      setState({ drawerOpen: true, drawerTab: tab });
      persist();
    };

    return html`
      <div class="header">
        <span class="brand">GRIPTAPE</span>
        <span
          class="fact"
          title=${
            "protocol " +
            (session.protocol_version || "-") +
            ", engine " +
            (session.engine_version || "-") +
            ", library " +
            (session.library_version || "-")
          }
        >
          <span class=${"dot " + dot}></span>
          <span class="clip">${st.session ? session.engine_name || "engine" : st.socket}</span>
        </span>
        <span class="fact">
          <span class="k">project</span>
          <span class="clip" title=${(st.currentProject && st.currentProject.workspace_dir) || ""}>
            ${(st.currentProject && st.currentProject.name) || "-"}
          </span>
        </span>
        <span class="fact">
          <span class="k">loaded</span>
          <span class="clip">
            ${(st.loaded && (st.loaded.name || st.loaded.workflow_id)) || "-"}
          </span>
        </span>
        <span class="grow"></span>
        ${st.runActive ? html`<span class="chip running">running</span>` : null}
        <button class="tiny" onClick=${() => open("wire")}>
          wire${st.frames.length ? " " + st.frames.length : ""}
        </button>
        <button class="tiny" onClick=${() => open("events")}>
          events${st.notifications.length ? " " + st.notifications.length : ""}
        </button>
        <button class="tiny" onClick=${() => open("connection")}>connection</button>
      </div>
    `;
  }

  function App() {
    const st = useStore();

    // No Connect button: this connects when it opens.
    useEffect(() => {
      guard(doConnect)();
    }, []);

    // Keeps elapsed time, the event rate, and the reconnect countdown moving between events, so a
    // stalled stream looks stalled rather than slow.
    useEffect(() => {
      if (!st.runActive && !st.drawerOpen) return undefined;
      const id = setInterval(() => setState({ tick: state().tick + 1 }), 500);
      return () => clearInterval(id);
    }, [st.runActive, st.drawerOpen]);

    return html`
      <${Header} st=${st} />
      ${
        st.banner
          ? html`<div class=${"banner " + st.banner.kind}>
              <div class="grow">
                <b>${st.banner.title}</b>
                <div>${st.banner.text}</div>
              </div>
              <button class="tiny" onClick=${() => setState({ banner: null })}>dismiss</button>
            </div>`
          : null
      }
      <div class="workspace">
        <div class="column">
          <${ProjectPane} st=${st} />
          <${WorkflowPane} st=${st} />
        </div>
        <div class="column">
          <${ParametersPane} st=${st} />
          <${RunPane} st=${st} />
        </div>
        <div class="column">
          <${OutputsPane} st=${st} />
          <${HistoryPane} st=${st} />
        </div>
      </div>
      ${st.drawerOpen ? html`<${Drawer} st=${st} />` : null}
    `;
  }

  Panes.App = App;
})();
