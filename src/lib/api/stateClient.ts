import { telemetry, type TelemetryData } from '$lib/stores/telemetry';
import { applyAuthToUrl, buildWsUrl, redactAuthFromUrl } from '$lib/api/client';

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
      // The query auth transport embeds the bearer token in the URL,
      // so log the redacted form (host + path preserved, token → `***`)
      // to avoid leaking credentials to DevTools / log aggregators.
      console.info('[helios] /state ws OPEN', { url: redactAuthFromUrl(url) });
    };

    ws.onmessage = (event) => {
      console.info('[helios] /state ws MSG raw', event.data);
      try {
        const frame = JSON.parse(event.data) as Partial<TelemetryData>;
        console.info('[helios] /state ws MSG parsed', frame);
        telemetry.applyLiveFrame(frame);
      } catch (err) {
        console.warn('[helios] /state ws MSG parse failed', err);
      }
    };

    ws.onerror = (event) => {
      console.warn('[helios] /state ws ERROR', event);
    };

    ws.onclose = (event) => {
      console.info('[helios] /state ws CLOSE', {
        code: event.code,
        reason: event.reason,
        wasClean: event.wasClean
      });
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
