// Keep transport and event ingestion independent by wiring their handlers here.
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
