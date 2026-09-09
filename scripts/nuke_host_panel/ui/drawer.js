// Everything a host author needs and a panel user never opens: the connection, the raw event
// stream, and the frames on the wire.
(function () {
  const { useMemo, useState } = preactHooks;
  const { NOTIFICATION } = Protocol;
  const { FRAME_LOG_LIMIT, LIVE_FEED_LIMIT, REPLY_TOPIC } = Config;
  const { guard, persist, setState } = Store;
  const { cancelReconnect, doConnect, doDisconnect, doDropSocket } = Session;
  const { Stat, html } = Ui;

  function ConnectionTab({ st }) {
    const session = st.session || {};
    const waiting = st.nextAttemptAt
      ? Math.max(0, Math.round((st.nextAttemptAt - Date.now()) / 1000))
      : null;

    return html`
      <div class="cols2">
        <div>
          <div class="sub">engine</div>
          <p class="note">
            The host and port are a host preference, never discovered: the engine's own registry
            files carry no compatibility promise.
          </p>
          <div class="field" style="margin-top: 6px">
            <label>engine</label>
            <input
              type="text"
              value=${st.wsUrl}
              onInput=${(e) => {
                setState({ wsUrl: e.target.value });
                persist();
              }}
            />
            <span></span>
          </div>
          <div class="field">
            <label>client_name</label>
            <input
              type="text"
              value=${st.clientName}
              onInput=${(e) => {
                setState({ clientName: e.target.value });
                persist();
              }}
            />
            <span></span>
          </div>
          <div class="stack" style="margin-top: 8px">
            <label>
              <input
                type="checkbox"
                checked=${st.autoConnect}
                onChange=${(e) => {
                  setState({ autoConnect: e.target.checked });
                  if (e.target.checked && !st.session) guard(doConnect)();
                  else cancelReconnect();
                }}
              />
              keep connected
            </label>
            <button disabled=${Boolean(st.session)} onClick=${guard(doConnect)}>Connect</button>
            <button disabled=${!st.autoConnect && !st.session} onClick=${doDisconnect}>
              Close
            </button>
            <button class="danger" disabled=${!st.session} onClick=${doDropSocket}>
              Drop the socket
            </button>
          </div>
          <div class="muted">
            Drop it under a live run: notifications sent while disconnected are gone, and the resync
            is what has to make up for it.
          </div>

          <table style="margin-top: 8px">
            <tbody>
              <tr>
                <th>socket</th>
                <td>${st.socket}</td>
              </tr>
              <tr>
                <th>protocol_version</th>
                <td>${session.protocol_version || "-"}</td>
              </tr>
              <tr>
                <th>engine_version</th>
                <td>${session.engine_version || "-"}</td>
              </tr>
              <tr>
                <th>library_version</th>
                <td>${session.library_version || "-"}</td>
              </tr>
              <tr>
                <th>engine_name</th>
                <td>${session.engine_name || "-"}</td>
              </tr>
              <tr>
                <th>engine_id</th>
                <td class="mono">${session.engine_id || "-"}</td>
              </tr>
              <tr>
                <th>session_id</th>
                <td class="mono">${session.session_id || "-"}</td>
              </tr>
              <tr>
                <th>event_topic</th>
                <td class="mono">
                  <span class=${"dot " + (st.subscribed.events ? "on" : "off")}></span>
                  ${session.event_topic || "-"}
                </td>
              </tr>
              <tr>
                <th>reply topic</th>
                <td class="mono">
                  <span class=${"dot " + (st.subscribed.reply ? "on" : "off")}></span>
                  ${REPLY_TOPIC}
                </td>
              </tr>
              <tr>
                <th>value_types</th>
                <td>${(session.value_types || []).join(", ") || "-"}</td>
              </tr>
              <tr>
                <th>attempts since success</th>
                <td>${st.connectAttempts}</td>
              </tr>
              <tr>
                <th>reconnects</th>
                <td>${st.reconnects}</td>
              </tr>
              <tr>
                <th>next attempt</th>
                <td>
                  ${
                    waiting === null
                      ? st.autoConnect
                        ? "not scheduled"
                        : "retry is off"
                      : "in " + waiting + "s"
                  }
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div>
          <div class="sub">resync</div>
          <p class="note">
            One sequence for first connect, reconnect, and page reload. Order is load-bearing:
            subscribe before requesting, or the reply is published to a topic this connection is not
            listening on.
          </p>
          ${
            !st.resyncSteps.length
              ? html`<div class="empty">Nothing has run yet.</div>`
              : st.resyncSteps.map(
                  (step, index) => html`
                    <div class="split">
                      <div class="stack">
                        <span
                          class=${
                            "chip " +
                            (step.outcome === "ok"
                              ? "resolved"
                              : step.outcome === "warn"
                                ? "running"
                                : "failed")
                          }
                        >
                          ${index + 1}
                        </span>
                        <span>${step.label}</span>
                      </div>
                      ${step.detail ? html`<div class="muted">${step.detail}</div>` : null}
                    </div>
                  `,
                )
          }
          <div class="sub" style="margin-top: 10px">stored locally</div>
          <div class="muted">
            Engine URL, client name, last workflow, and parameter values, per engine id. None of it
            is protocol.
          </div>
          <div class="stack" style="margin-top: 4px">
            <button
              class="tiny"
              onClick=${() => {
                setState({ engines: {}, restored: 0 });
                persist();
              }}
            >
              forget
            </button>
            <span class="muted">${Object.keys(st.engines).length} engine(s) remembered</span>
          </div>
        </div>
      </div>
    `;
  }

  function typeClass(payloadType) {
    if (payloadType === NOTIFICATION.NODE_STATE) return "ev-node";
    if (payloadType === NOTIFICATION.PARAMETER_VALUE) return "ev-value";
    if (payloadType === NOTIFICATION.EXECUTION_STATE) return "ev-exec";
    if (payloadType === NOTIFICATION.EXECUTION_NODES) return "ev-nodes";
    return "";
  }

  function EventsTab({ st }) {
    const now = Date.now();
    const streaming = st.lastEventAt && now - st.lastEventAt < 2000;
    const recent = st.feed.filter((entry) => now - entry.at < 3000);

    return html`
      <div>
        <p class="note">
          Nothing here was requested: every row arrived on the event topic, and the request counter
          stops moving while the feed fills. A run started anywhere on this engine appears here.
          "elsewhere" is inferred, since the protocol carries no execution id.
        </p>
        <div class="stats" style="margin: 8px 0">
          <${Stat}
            label="stream"
            value=${!st.session ? "offline" : streaming ? "receiving" : "listening"}
            accent=${streaming ? "hot" : ""}
          />
          <${Stat} label="events" value=${st.notifications.length} />
          <${Stat} label="events/sec" value=${(recent.length / 3).toFixed(1)} />
          <${Stat} label="requests sent" value=${st.requestsSent} />
          <${Stat}
            label="requests this run"
            value=${st.requestsDuringRun}
            accent=${st.runOrigin && st.requestsDuringRun === 0 ? "hot" : ""}
          />
          <${Stat} label="started by" value=${st.runOrigin || "-"} />
        </div>
        <div class="stack" style="margin-bottom: 4px">
          <button class="tiny" onClick=${() => setState({ feed: [] })}>clear</button>
          <span class="muted">newest first, capped at ${LIVE_FEED_LIMIT}</span>
        </div>
        <div class="feed">
          ${
            !st.feed.length
              ? html`<div class="empty">Nothing yet.</div>`
              : st.feed
                  .slice()
                  .reverse()
                  .map(
                    (entry) => html`
                      <div class=${"ev" + (entry.foreign ? " foreign" : "")}>
                        <span class="dt"
                          >${entry.delta === null ? "" : "+" + entry.delta + "ms"}</span
                        >
                        <span class=${"ty " + typeClass(entry.type)}>${entry.type}</span>
                        <span>${entry.summary}</span>
                      </div>
                    `,
                  )
          }
        </div>
      </div>
    `;
  }

  function Frame({ entry }) {
    const [open, setOpen] = useState(false);
    return html`
      <div>
        <div class="frame" onClick=${() => setOpen(!open)}>
          <span class=${"dir " + entry.direction}>
            ${entry.direction === "out" ? "\u2192" : "\u2190"}
          </span>
          <span class="ts">${entry.at.toISOString().slice(11, 23)}</span>
          <span class="kind">${entry.type}</span>
          <span class="what">${entry.what}</span>
          <span class="rid">${entry.requestId ? entry.requestId.slice(0, 8) : ""}</span>
        </div>
        ${open ? html`<pre class="json">${JSON.stringify(entry.frame, null, 2)}</pre>` : null}
      </div>
    `;
  }

  function WireTab({ st }) {
    const filter = st.frameFilter.trim().toLowerCase();
    const visible = useMemo(
      () =>
        st.frames.filter((entry) =>
          filter
            ? (entry.type + " " + entry.what + " " + entry.requestId)
                .toLowerCase()
                .indexOf(filter) !== -1
            : true,
        ),
      [st.frames, filter],
    );

    return html`
      <div>
        <div class="stack" style="margin-bottom: 6px">
          <input
            type="text"
            style="width: 240px"
            placeholder="filter by type, request_type, payload_type, id"
            value=${st.frameFilter}
            onInput=${(e) => setState({ frameFilter: e.target.value })}
          />
          <button class="tiny" onClick=${() => setState({ frames: [] })}>clear</button>
          <span class="muted">
            ${visible.length} of ${st.frames.length} frames, capped at ${FRAME_LOG_LIMIT}
          </span>
        </div>
        ${
          !visible.length
            ? html`<div class="empty">No frames match.</div>`
            : visible
                .slice()
                .reverse()
                .map(
                  (entry, i) =>
                    html`<${Frame} key=${entry.at.getTime() + "-" + i} entry=${entry} />`,
                )
        }
      </div>
    `;
  }

  const TABS = [
    ["connection", "Connection"],
    ["events", "Events"],
    ["wire", "Wire"],
  ];

  function Drawer({ st }) {
    return html`
      <div class="drawer">
        <div class="tabs">
          ${TABS.map(
            ([id, label]) => html`
              <button
                class=${st.drawerTab === id ? "active" : ""}
                onClick=${() => {
                  setState({ drawerTab: id });
                  persist();
                }}
              >
                ${label}
              </button>
            `,
          )}
          <span class="grow"></span>
          <button
            class="tiny"
            onClick=${() => {
              setState({ drawerOpen: false });
              persist();
            }}
          >
            hide
          </button>
        </div>
        <div class="content">
          ${st.drawerTab === "connection" ? html`<${ConnectionTab} st=${st} />` : null}
          ${st.drawerTab === "events" ? html`<${EventsTab} st=${st} />` : null}
          ${st.drawerTab === "wire" ? html`<${WireTab} st=${st} />` : null}
        </div>
      </div>
    `;
  }

  Panes.Drawer = Drawer;
})();
