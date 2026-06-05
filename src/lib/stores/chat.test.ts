import { describe, it, expect, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import { chat, type ChatMessage } from './chat.js';

describe('chat store', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  // --- Initial State ---
  describe('initial state', () => {
    it('exposes a subscribe method', () => {
      expect(chat.subscribe).toBeTypeOf('function');
    });

    it('starts with exactly 1 initial message', () => {
      const messages = get(chat);
      expect(messages).toHaveLength(1);
    });

    it('the initial message is from aegis', () => {
      const messages = get(chat);
      expect(messages[0].sender).toBe('aegis');
    });

    it('the initial message has non-empty text', () => {
      const messages = get(chat);
      expect(messages[0].text.length).toBeGreaterThan(0);
    });

    it('the initial message has a timestamp string', () => {
      const messages = get(chat);
      expect(messages[0].timestamp).toBeTypeOf('string');
      expect(messages[0].timestamp.length).toBeGreaterThan(0);
    });

    it('the initial message has a stable unique id', () => {
      const messages = get(chat);
      expect(messages[0].id).toBeTypeOf('string');
      expect(messages[0].id.length).toBeGreaterThan(0);
    });
  });

  // --- sendMessage ---
  describe('sendMessage()', () => {
    it('exposes a sendMessage method', () => {
      expect(chat.sendMessage).toBeTypeOf('function');
    });

    it('appends a user message immediately', () => {
      vi.useFakeTimers();

      const before = get(chat);
      const countBefore = before.length;

      chat.sendMessage('Hello Aegis');

      const after = get(chat);
      expect(after.length).toBe(countBefore + 1);
      expect(after[after.length - 1].sender).toBe('you');
      expect(after[after.length - 1].text).toBe('Hello Aegis');
      expect(after[after.length - 1].id).toBeTypeOf('string');
      expect(after[after.length - 1].id.length).toBeGreaterThan(0);
    });

    it('user message has a timestamp', () => {
      vi.useFakeTimers();

      chat.sendMessage('timestamp test');

      const messages = get(chat);
      const userMessage = messages[messages.length - 1];
      expect(userMessage.timestamp).toBeTypeOf('string');
      expect(userMessage.timestamp.length).toBeGreaterThan(0);
    });

    it('does not trigger aegis reply synchronously', () => {
      vi.useFakeTimers();

      const countBefore = get(chat).length;
      chat.sendMessage('sync check');

      // Immediately after - only user message added, no aegis reply yet
      const immediate = get(chat);
      expect(immediate.length).toBe(countBefore + 1);
      expect(immediate[immediate.length - 1].sender).toBe('you');
    });

    it('triggers aegis reply after 1500ms', () => {
      vi.useFakeTimers();

      const countBefore = get(chat).length;
      chat.sendMessage('please reply');

      vi.advanceTimersByTime(1500);

      const after = get(chat);
      // user message + aegis reply = 2 new messages
      expect(after.length).toBe(countBefore + 2);
      expect(after[after.length - 1].sender).toBe('aegis');
    });

    it('aegis reply has non-empty text from mock replies', () => {
      vi.useFakeTimers();

      chat.sendMessage('test');
      vi.advanceTimersByTime(1500);

      const messages = get(chat);
      const aegisReply = messages[messages.length - 1];
      expect(aegisReply.text.length).toBeGreaterThan(0);
    });

    it('aegis reply is sent with the same timestamp as the user message', () => {
      vi.useFakeTimers();

      // Fix the time so toLocaleTimeString returns a consistent value
      const fixedDate = new Date('2026-06-05T14:30:00Z');
      vi.setSystemTime(fixedDate);

      chat.sendMessage('time test');
      const userMessage = get(chat)[get(chat).length - 1];

      vi.advanceTimersByTime(1500);

      const messages = get(chat);
      const aegisReply = messages[messages.length - 1];

      // Both user message and aegis reply capture time at send time
      expect(aegisReply.timestamp).toBe(userMessage.timestamp);
    });

    it('does not trigger aegis reply before 1500ms', () => {
      vi.useFakeTimers();

      const countBefore = get(chat).length;
      chat.sendMessage('early check');

      vi.advanceTimersByTime(1499);

      const after = get(chat);
      // Only user message added so far
      expect(after.length).toBe(countBefore + 1);
      expect(after[after.length - 1].sender).toBe('you');
    });

    it('aegis reply text is one of the known mock replies', () => {
      vi.useFakeTimers();

      const knownReplies = [
        'Acknowledge. Proceeding with standard background checks.',
        'Uptime and memory allocation levels are within target metrics.',
        'Analyzing neural pathways. Drift levels remain negligible.',
        'I will alert you immediately if coherence dips below 0.83.',
        'Task successfully added to roadmap queue.',
        'Diagnostics clear. System operating at 9.8 tick/s.'
      ];

      chat.sendMessage('what are your replies?');
      vi.advanceTimersByTime(1500);

      const messages = get(chat);
      const aegisReply = messages[messages.length - 1];
      expect(knownReplies).toContain(aegisReply.text);
    });

    it('preserves message order: previous messages remain at earlier indices', () => {
      vi.useFakeTimers();

      const initialMessages = get(chat);
      const initialFirst = initialMessages[0];

      chat.sendMessage('order test');
      vi.advanceTimersByTime(1500);

      const messages = get(chat);
      expect(messages[0]).toEqual(initialFirst);
    });

    it('can handle multiple sends sequentially', () => {
      vi.useFakeTimers();

      const countBefore = get(chat).length;

      chat.sendMessage('first message');
      vi.advanceTimersByTime(1500);

      chat.sendMessage('second message');
      vi.advanceTimersByTime(1500);

      const messages = get(chat);
      // 2 user messages + 2 aegis replies = 4 new messages
      expect(messages.length).toBe(countBefore + 4);

      // Verify ordering: user1, aegis1, user2, aegis2
      const newMessages = messages.slice(countBefore);
      expect(newMessages[0].sender).toBe('you');
      expect(newMessages[0].text).toBe('first message');
      expect(newMessages[1].sender).toBe('aegis');
      expect(newMessages[2].sender).toBe('you');
      expect(newMessages[2].text).toBe('second message');
      expect(newMessages[3].sender).toBe('aegis');
    });

    it('handles empty string message without throwing', () => {
      vi.useFakeTimers();

      expect(() => {
        chat.sendMessage('');
      }).not.toThrow();

      const messages = get(chat);
      const lastMsg = messages[messages.length - 1];
      expect(lastMsg.sender).toBe('you');
      expect(lastMsg.text).toBe('');
    });
  });

  // --- clearHistory ---
  describe('clearHistory()', () => {
    it('exposes a clearHistory method', () => {
      expect(chat.clearHistory).toBeTypeOf('function');
    });

    it('empties the messages array', () => {
      chat.sendMessage('Test message');
      chat.clearHistory();
      const messages = get(chat);
      expect(messages).toHaveLength(0);
    });
  });

  // --- Subscription ---
  describe('subscription', () => {
    it('calls subscriber immediately with current state', () => {
      const snapshots: ChatMessage[][] = [];
      const unsubscribe = chat.subscribe((v) => snapshots.push(v));
      unsubscribe();

      expect(snapshots).toHaveLength(1);
      expect(Array.isArray(snapshots[0])).toBe(true);
    });

    it('notifies subscribers when a message is sent', () => {
      vi.useFakeTimers();

      const snapshots: ChatMessage[][] = [];
      const unsubscribe = chat.subscribe((v) => snapshots.push([...v]));

      const callsBefore = snapshots.length;
      chat.sendMessage('subscriber notification test');

      unsubscribe();

      expect(snapshots.length).toBeGreaterThan(callsBefore);
      const lastSnapshot = snapshots[snapshots.length - 1];
      expect(lastSnapshot[lastSnapshot.length - 1].text).toBe('subscriber notification test');
    });

    it('notifies subscribers when aegis replies', () => {
      vi.useFakeTimers();

      const snapshots: ChatMessage[][] = [];
      const unsubscribe = chat.subscribe((v) => snapshots.push([...v]));

      chat.sendMessage('reply notification test');
      const snapshotsBeforeReply = snapshots.length;

      vi.advanceTimersByTime(1500);

      unsubscribe();

      expect(snapshots.length).toBeGreaterThan(snapshotsBeforeReply);
      const lastSnapshot = snapshots[snapshots.length - 1];
      expect(lastSnapshot[lastSnapshot.length - 1].sender).toBe('aegis');
    });
  });

  // --- ChatMessage Interface ---
  describe('ChatMessage interface shape', () => {
    it('initial message conforms to ChatMessage shape', () => {
      const messages = get(chat);
      const msg = messages[0];

      expect(msg).toHaveProperty('sender');
      expect(msg).toHaveProperty('text');
      expect(msg).toHaveProperty('timestamp');
      // affect is optional
    });

    it('sender field is either "aegis" or "you"', () => {
      vi.useFakeTimers();

      chat.sendMessage('shape test');
      vi.advanceTimersByTime(1500);

      const messages = get(chat);
      for (const msg of messages) {
        expect(['aegis', 'you']).toContain(msg.sender);
      }
    });
  });
});
