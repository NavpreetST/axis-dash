import { createStateClient } from './stateClient';
import { createLogsClient } from './logsClient';
import { createChatClient } from './chatClient';

export interface BridgeClients {
  state: ReturnType<typeof createStateClient>;
  logs: ReturnType<typeof createLogsClient>;
  chat: ReturnType<typeof createChatClient>;
}

export function startBridge(): BridgeClients {
  const state = createStateClient();
  const logs = createLogsClient();
  const chat = createChatClient();
  state.connect();
  logs.connect();
  chat.connect();
  return { state, logs, chat };
}

export function stopBridge(clients: BridgeClients) {
  clients.state.disconnect();
  clients.logs.disconnect();
  clients.chat.disconnect();
}
