// Shared presentation helpers, and the namespace the pane files below fill in.
// Everything from here down is presentation only.
const Panes = {};

const Ui = (function () {
  const { h } = preact;
  const { useEffect, useState } = preactHooks;
  const { state, subscribeToStore } = Store;

  const html = htm.bind(h);

  function useStore() {
    const [, bump] = useState(0);
    useEffect(() => subscribeToStore(() => bump((n) => n + 1)), []);
    return state();
  }

  // An unknown state gets its own class rather than no class: a new member of an enum must be
  // visible, not invisible.
  const stateClass = (value, known) => (known.indexOf(value) === -1 ? "unknown" : value);

  const clock = (ms) => new Date(ms).toTimeString().slice(0, 8);

  function copyButton(text, label) {
    return html`<button
      class="tiny"
      onClick=${() => navigator.clipboard && navigator.clipboard.writeText(text || "")}
    >
      ${label || "copy"}
    </button>`;
  }

  function Stat({ label, value, accent }) {
    return html`
      <div class="stat">
        <div class="k">${label}</div>
        <div class=${"v" + (accent ? " " + accent : "")}>${value}</div>
      </div>
    `;
  }

  return {
    html,
    useStore,
    stateClass,
    clock,
    copyButton,
    Stat,
  };
})();
