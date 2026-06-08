import { logs, type LogLine } from '$lib/stores/logs';
import { applyAuthToUrl, buildSseUrl } from '$lib/api/client';

/** Upper bound (ms) for the exponential reconnect backoff. */
const MAX_RECONNECT_DELAY = 30000;
/**
 * Initial reconnect delay (ms) for the logs stream. Slightly longer
 * than the state/chat clients (1000ms) so the first reconnect attempt
 * does not collide with the state/chat sockets hammering the bridge
 * during a cold start. Doubled per attempt up to {@link MAX_RECONNECT_DELAY}.
 */
const INITIAL_RECONNECT_DELAY = 2000;

/**
 * Server-Sent Events client for the live `/logs` stream.
 *
 * Each event payload is parsed as JSON and converted into the existing
 * `LogLine` shape, then pushed into the logs store. Malformed payloads
 * are coerced into a generic `info` entry so nothing is silently dropped.
 * Reconnects with capped exponential backoff on error.
 */
export function createLogsClient() {
  let es: EventSource | null = null;
  let reconnectAttempts = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  const connect = () => {
    if (stopped) return;
    const url = applyAuthToUrl(buildSseUrl('/logs'));
    try {
      es = new EventSource(url);
    } catch {
      scheduleReconnect();
      return;
    }

    es.onopen = () => {
      reconnectAttempts = 0;
      logs.setConnected(true);
    };

    es.onmessage = (event) => {
      try {
        const raw = JSON.parse(event.data);
        const entry: Omit<LogLine, 'id' | 'timestamp'> = {
          source: raw.source ?? 'sys',
          type: raw.type ?? 'info',
          message: raw.message ?? String(event.data)
        };
        logs.addLog(entry);
      } catch {
        logs.addLog({ source: 'sys', type: 'info', message: String(event.data) });
      }
    };

    es.onerror = () => {
      logs.setConnected(false);
      if (es) {
        es.close();
        es = null;
      }
      scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (stopped) return;
    logs.setConnected(false);
    const delay = Math.min(
      MAX_RECONNECT_DELAY,
      INITIAL_RECONNECT_DELAY * Math.pow(2, reconnectAttempts)
    );
    reconnectAttempts++;
    reconnectTimer = setTimeout(connect, delay);
  };

  const disconnect = () => {
    stopped = true;
    logs.setConnected(false);
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (es) {
      es.onmessage = null;
      es.onerror = null;
      es.onopen = null;
      es.close();
      es = null;
    }
  };

  return { connect, disconnect };
}
