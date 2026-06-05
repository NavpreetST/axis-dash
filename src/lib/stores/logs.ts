import { writable } from 'svelte/store';

export interface LogLine {
  id: string;
  timestamp: string;
  source: string;
  type: 'info' | 'success' | 'warning' | 'error';
  message: string;
}

const initialLogs: LogLine[] = [
  {
    id: 'seed-log-1',
    timestamp: '14:22:08',
    source: 'tick',
    type: 'info',
    message: 'orb pulse • coherence 0.912 • drift 0.04'
  },
  {
    id: 'seed-log-2',
    timestamp: '14:22:06',
    source: 'mem',
    type: 'success',
    message: 'embedding flushed • 1,284 vec • 38ms'
  },
  {
    id: 'seed-log-3',
    timestamp: '14:22:03',
    source: 'sys',
    type: 'info',
    message: 'gemini ok • groq ok • rpd 37/240'
  },
  {
    id: 'seed-log-4',
    timestamp: '14:21:58',
    source: 'task',
    type: 'success',
    message: 'todo:resolve#812 -> completed by aegis'
  }
];

const mockMessages: Omit<LogLine, 'timestamp' | 'id'>[] = [
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

  const addLog = (log: Omit<LogLine, 'timestamp' | 'id'>) => {
    const time = new Date().toLocaleTimeString('en-US', { hour12: false });
    const id =
      typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `log-${Math.random().toString(36).substring(2, 9)}`;
    update((logs) => [{ id, timestamp: time, ...log }, ...logs].slice(0, 100));
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

  const clearLogs = () => {
    update(() => []);
  };

  return {
    subscribe,
    start,
    stop,
    addLog,
    clearLogs
  };
};

export const logs = createLogsStore();
