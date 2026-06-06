import { writable } from 'svelte/store';

export interface ChatMessage {
  id: string;
  sender: 'aegis' | 'you';
  text: string;
  timestamp: string;
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

type LiveSender = (text: string) => boolean;

const createChatStore = () => {
  const { subscribe, update } = writable<ChatMessage[]>(initialMessages);
  let liveSender: LiveSender | null = null;

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

  const clearHistory = () => {
    update(() => []);
  };

  const pushMessage = (msg: ChatMessage) => {
    update((messages) => [...messages, msg]);
  };

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

export const chat = createChatStore();
