import { config } from '$lib/config';
import { telemetry } from '$lib/stores/telemetry';
import { getToken, applyAuthToUrl, buildHttpUrl, buildWsUrl } from './client';
import { createStateClient } from './stateClient';
import { createLogsClient } from './logsClient';
import { createChatClient } from './chatClient';

/** Bundle of all live bridge clients, returned by {@link startBridge}. */
export interface BridgeClients {
  state: ReturnType<typeof createStateClient>;
  logs: ReturnType<typeof createLogsClient>;
  chat: ReturnType<typeof createChatClient>;
}

/**
 * Start the live bridge.
 *
 * - Clears the seeded mock telemetry snapshot so the UI shows `--`
 *   placeholders until the first `/state` frame arrives.
 * - Logs a single info line summarising the resolved endpoints and
 *   auth status so the next deploy makes it obvious in DevTools
 *   whether the live code path actually ran.
 * - Opens the state, logs, and chat streams.
 */
export function startBridge(): BridgeClients {
  telemetry.resetToUnknown();

  const token = getToken();
  if (typeof console !== 'undefined') {
    const stateUrl = applyAuthToUrl(buildWsUrl('/state'));
    const chatUrl = applyAuthToUrl(buildWsUrl('/chat'));
    const logsUrl = applyAuthToUrl(buildHttpUrl('/logs'));
    console.info('[helios] live bridge starting', {
      api: config.heliosApiUrl,
      ws: config.heliosWsUrl,
      auth: token ? 'token present' : 'NO TOKEN — set PUBLIC_HELIOS_TOKEN or log in',
      targets: { stateUrl, chatUrl, logsUrl }
    });
  }

  const state = createStateClient();
  const logs = createLogsClient();
  const chat = createChatClient();
  state.connect();
  logs.connect();
  chat.connect();
  return { state, logs, chat };
}

/** Tear down every client in the bridge bundle. Idempotent. */
export function stopBridge(clients: BridgeClients) {
  clients.state.disconnect();
  clients.logs.disconnect();
  clients.chat.disconnect();
}
