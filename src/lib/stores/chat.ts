import { writable } from 'svelte/store';

/** A single chat bubble rendered in the Aegis terminal panel. */
export interface ChatMessage {
  id: string;
  sender: 'aegis' | 'you';
  text: string;
  timestamp: string;
  /** Optional indicator of emotional state / theme for the message. */
  affect?: string;
}

const initialMessages: ChatMessage[] = [
  {
    id: 'seed-chat-1',
    sender: 'aegis',
    text: 'Coherence stable at 0.91. Drift is soft, within tolerance. Nothing urgent on the board.',
    timestamp: '18:04'
  }
];

const mockAegisReplies = [
  'Acknowledge. Proceeding with standard background checks.',
  'Uptime and memory allocation levels are within target metrics.',
  'Analyzing neural pathways. Drift levels remain negligible.',
  'I will alert you immediately if coherence dips below 0.83.',
  'Task successfully added to roadmap queue.',
  'Diagnostics clear. System operating at 9.8 tick/s.'
];

/** Callback the chat store delegates outbound messages to. Returns true if accepted. */
type LiveSender = (text: string) => boolean;

const createChatStore = () => {
  const { subscribe, update } = writable<ChatMessage[]>(initialMessages);
  let liveSender: LiveSender | null = null;

  /**
   * Send a user message. If a live sender is registered and accepts
   * the text, no mock reply is generated. Otherwise a mock Aegis
   * reply is appended after ~1.5s.
   */
  const sendMessage = (text: string) => {
    const time = new Date().toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });

    const userMsgId =
      typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `chat-${Math.random().toString(36).substring(2, 9)}`;

    update((messages) => [...messages, { id: userMsgId, sender: 'you', text, timestamp: time }]);

    if (liveSender && liveSender(text)) {
      return;
    }

    const aegisReplyId =
      typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `chat-${Math.random().toString(36).substring(2, 9)}`;

    setTimeout(() => {
      const reply = mockAegisReplies[Math.floor(Math.random() * mockAegisReplies.length)];
      update((messages) => [
        ...messages,
        { id: aegisReplyId, sender: 'aegis', text: reply, timestamp: time }
      ]);
    }, 1500);
  };

  /** Wipe all chat history. */
  const clearHistory = () => {
    update(() => []);
  };

  /**
   * Append a fully-formed message from outside the store. Used by the
   * live chat client to inject incoming Aegis replies.
   */
  const pushMessage = (msg: ChatMessage) => {
    update((messages) => [...messages, msg]);
  };

  /**
   * Register (or clear) the live sender. When set, `sendMessage` will
   * delegate outbound frames to it instead of using the mock reply.
   */
  const setLiveSender = (sender: LiveSender | null) => {
    liveSender = sender;
  };

  return {
    subscribe,
    sendMessage,
    clearHistory,
    pushMessage,
    setLiveSender
  };
};

/**
 * Shared chat store. Drives the Aegis terminal sidebar. In live mode
 * it delegates outbound sends to the bridge WS and accepts incoming
 * replies via `pushMessage`; otherwise it uses the local mock.
 */
export const chat = createChatStore();
