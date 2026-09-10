const Config = (function () {
  const REPLY_TOPIC = "nuke-host-browser/reply";

  const REQUEST_TIMEOUT_MS = 60000;
  // Missing request handlers fail silently, so connect uses a shorter timeout.
  const CONNECT_TIMEOUT_MS = 12000;
  // Execute replies after the run; zero disables its timeout.
  const EXECUTE_TIMEOUT_MS = 0;

  // Trailing parameter values follow the terminal event, so outputs are read after a grace period.
  const DRAIN_GRACE_MS = 800;

  const RECONNECT_BACKOFF_MS = [1000, 2000, 4000, 8000, 15000, 30000];
  // Coalesce edits to avoid one round trip per keystroke.
  const WRITE_THROUGH_DEBOUNCE_MS = 400;
  // Polling covers dropped fire-and-forget events, which have no replay.
  const POLL_TICK_MS = 2500;

  const FRAME_LOG_LIMIT = 400;
  const LIVE_FEED_LIMIT = 200;
  const HISTORY_LIMIT = 12;

  const SETTINGS_KEY = "nuke-host-panel/v1";
  const DEFAULT_WS_URL = "ws://127.0.0.1:18125";
  const DEFAULT_CLIENT_NAME = "browser host panel";

  return {
    REPLY_TOPIC,
    REQUEST_TIMEOUT_MS,
    CONNECT_TIMEOUT_MS,
    EXECUTE_TIMEOUT_MS,
    DRAIN_GRACE_MS,
    RECONNECT_BACKOFF_MS,
    WRITE_THROUGH_DEBOUNCE_MS,
    POLL_TICK_MS,
    FRAME_LOG_LIMIT,
    LIVE_FEED_LIMIT,
    HISTORY_LIMIT,
    SETTINGS_KEY,
    DEFAULT_WS_URL,
    DEFAULT_CLIENT_NAME,
  };
})();
