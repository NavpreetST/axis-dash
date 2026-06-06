import { chat, type ChatMessage } from '$lib/stores/chat';
import { applyAuthToUrl, buildWsUrl } from '$lib/api/client';

/** Upper bound (ms) for the exponential reconnect backoff. */
const MAX_RECONNECT_DELAY = 30000;
/** Initial reconnect delay (ms); doubled per attempt up to {@link MAX_RECONNECT_DELAY}. */
const INITIAL_RECONNECT_DELAY = 1000;

/**
 * WebSocket client for the live `/chat` stream.
 *
 * Receives one Aegis reply per incoming frame (plain text), wraps it in
 * a `ChatMessage`, and pushes it to the chat store. Outbound messages
 * are sent as plain text frames to match the current bridge contract
 * (no JSON protocol is invented here).
 *
 * Reconnects with capped exponential backoff on close. `send()` returns
 * `false` if the socket is not open, so callers can fall back to the
 * mock reply if needed.
 */
export function createChatClient() {
  let ws: WebSocket | null = null;
  let reconnectAttempts = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  const connect = () => {
    if (stopped) return;
    const url = applyAuthToUrl(buildWsUrl('/chat'));
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      reconnectAttempts = 0;
    };

    ws.onmessage = (event) => {
      const text = typeof event.data === 'string' ? event.data : '';
      if (!text) return;
      const time = new Date().toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
      });
      const id =
        typeof crypto !== 'undefined' && crypto.randomUUID
          ? crypto.randomUUID()
          : `chat-${Math.random().toString(36).substring(2, 9)}`;
      const msg: ChatMessage = {
        id,
        sender: 'aegis',
        text,
        timestamp: time
      };
      chat.pushMessage(msg);
    };

    ws.onerror = () => {
      // onclose will fire next
    };

    ws.onclose = () => {
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

  /**
   * Send a chat message to the bridge. Returns `true` when the frame
   * was handed to an open socket, `false` otherwise (caller may then
   * fall back to the local mock reply).
   */
  const send = (text: string): boolean => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(text);
    return true;
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

  return { connect, disconnect, send };
}
