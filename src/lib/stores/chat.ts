import { writable } from 'svelte/store';

export interface ChatMessage {
  sender: 'aegis' | 'you';
  text: string;
  timestamp: string;
  affect?: string; // Optional indicator of emotional state/theme
}

const initialMessages: ChatMessage[] = [
  {
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

const createChatStore = () => {
  const { subscribe, update } = writable<ChatMessage[]>(initialMessages);

  const sendMessage = (text: string) => {
    const time = new Date().toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });

    // Append user message
    update((messages) => [...messages, { sender: 'you', text, timestamp: time }]);

    // Trigger mock Aegis reply after a short delay
    setTimeout(() => {
      const reply = mockAegisReplies[Math.floor(Math.random() * mockAegisReplies.length)];
      update((messages) => [...messages, { sender: 'aegis', text: reply, timestamp: time }]);
    }, 1500);
  };

  return {
    subscribe,
    sendMessage
  };
};

export const chat = createChatStore();
