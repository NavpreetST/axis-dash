import { telemetry } from '$lib/stores/telemetry';
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
 * Start the live bridge. Clears the seeded mock telemetry snapshot so
 * the UI shows `--` placeholders until the first `/state` frame
 * arrives, then opens the state, logs, and chat streams.
 */
export function startBridge(): BridgeClients {
  telemetry.resetToUnknown();
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
