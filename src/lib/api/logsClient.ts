import { logs, type LogLine } from '$lib/stores/logs';
import { applyAuthToUrl, buildSseUrl } from '$lib/api/client';

const MAX_RECONNECT_DELAY = 30000;
const INITIAL_RECONNECT_DELAY = 2000;

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
      if (es) {
        es.close();
        es = null;
      }
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
    if (es) {
      es.onmessage = null;
      es.onerror = null;
      es.close();
      es = null;
    }
  };

  return { connect, disconnect };
}
