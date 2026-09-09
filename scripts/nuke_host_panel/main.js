// Entry point. Wires the three seams between transport, event ingestion, and actions, then renders.
//
// The wiring lives here rather than inside those files so none of them has to reach for another:
// transport knows nothing about engine semantics, and event ingestion knows nothing about what a
// finished run means.
//
// Plain scripts rather than ES modules, loaded in dependency order by index.html, so this opens
// straight off the filesystem: a file:// page cannot import a module from a sibling file.
(function () {
  Transport.setHandlers({
    onNotification: Events.dispatchNotification,
    onClose: Session.onSocketClosed,
  });
  Events.setEventHooks({ onTerminal: Actions.finishRun });

  const root = document.getElementById("app");
  clearTimeout(window.__bootTimer);
  root.dataset.rendered = "1";
  root.classList.remove("booting");
  root.innerHTML = "";
  preact.render(Ui.html`<${Panes.App} />`, root);
})();
