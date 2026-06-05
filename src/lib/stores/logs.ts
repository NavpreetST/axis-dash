import { writable } from 'svelte/store';

export interface LogLine {
  timestamp: string;
  source: string;
  type: 'info' | 'success' | 'warning' | 'error';
  message: string;
}

const initialLogs: LogLine[] = [
  {
    timestamp: '14:22:08',
    source: 'tick',
    type: 'info',
    message: 'orb pulse • coherence 0.912 • drift 0.04'
  },
  {
    timestamp: '14:22:06',
    source: 'mem',
    type: 'success',
    message: 'embedding flushed • 1,284 vec • 38ms'
  },
  {
    timestamp: '14:22:03',
    source: 'sys',
    type: 'info',
    message: 'gemini ok • groq ok • rpd 37/240'
  },
  {
    timestamp: '14:21:58',
    source: 'task',
    type: 'success',
    message: 'todo:resolve#812 -> completed by aegis'
  }
];

const mockMessages: Omit<LogLine, 'timestamp'>[] = [
  { source: 'tick', type: 'info', message: 'orb pulse • coherence 0.914 • drift 0.03' },
  { source: 'sys', type: 'info', message: 'model check • latency 182ms' },
  { source: 'mem', type: 'success', message: 'episodic memory consolidation finished' },
  { source: 'task', type: 'info', message: 'polling pending issues from Notion...' },
  { source: 'sys', type: 'warning', message: 'Gemini request latency elevated (1.2s)' },
  { source: 'mem', type: 'info', message: 'T1 memory cache hit rate 94.2%' },
  { source: 'tick', type: 'info', message: 'PAM check • Coherence stable at 0.91' }
];

const createLogsStore = () => {
  const { subscribe, update } = writable<LogLine[]>(initialLogs);
  let timer: ReturnType<typeof setTimeout> | null = null;

  const addLog = (log: Omit<LogLine, 'timestamp'>) => {
    const time = new Date().toLocaleTimeString('en-US', { hour12: false });
    update((logs) => [{ timestamp: time, ...log }, ...logs].slice(0, 100));
  };

  const start = () => {
    if (timer) return;
    const scheduleNext = () => {
      const delay = Math.random() * 5000 + 3000; // 3 to 8 seconds
      timer = setTimeout(() => {
        const template = mockMessages[Math.floor(Math.random() * mockMessages.length)];
        addLog({
          source: template.source,
          type: template.type,
          message: template.message
        });
        scheduleNext();
      }, delay);
    };
    scheduleNext();
  };

  const stop = () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  };

  return {
    subscribe,
    start,
    stop,
    addLog
  };
};

export const logs = createLogsStore();
