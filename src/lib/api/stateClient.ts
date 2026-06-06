import { telemetry, type TelemetryData } from '$lib/stores/telemetry';
import { applyAuthToUrl, buildWsUrl } from '$lib/api/client';

/** Upper bound (ms) for the exponential reconnect backoff. */
const MAX_RECONNECT_DELAY = 30000;
/** Initial reconnect delay (ms); doubled per attempt up to {@link MAX_RECONNECT_DELAY}. */
const INITIAL_RECONNECT_DELAY = 1000;

/**
 * WebSocket client for the live `/state` stream.
 *
 * Connects to the bridge, parses each JSON frame into a partial
 * `TelemetryData` update, and forwards it to the telemetry store.
 * Reconnects with capped exponential backoff on close or error and
 * flips `telemetry.connected` to mirror the socket state so the UI
 * falls back to `--` placeholders while disconnected.
 */
export function createStateClient() {
  let ws: WebSocket | null = null;
  let reconnectAttempts = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  const connect = () => {
    if (stopped) return;
    const url = applyAuthToUrl(buildWsUrl('/state'));
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      reconnectAttempts = 0;
      telemetry.setConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const frame = JSON.parse(event.data) as Partial<TelemetryData>;
        telemetry.applyLiveFrame(frame);
      } catch {
        // ignore malformed frame
      }
    };

    ws.onerror = () => {
      // onclose will fire next
    };

    ws.onclose = () => {
      telemetry.setConnected(false);
      scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (stopped) return;
    const delay = Math.min(
      MAX_RECONNECT_DELAY,
      INITIAL_RECONNECT_DELAY * Math.pow(2, reconnectAttempts)
    );
    reconnectAttempts++;
    reconnectTimer = setTimeout(connect, delay);
  };

  const disconnect = () => {
    stopped = true;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws) {
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      ws.close();
      ws = null;
    }
  };

  return { connect, disconnect };
}
