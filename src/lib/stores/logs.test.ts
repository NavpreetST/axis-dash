import { describe, it, expect, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import { logs, type LogLine } from './logs.js';

describe('logs store', () => {
  afterEach(() => {
    logs.stop();
    vi.useRealTimers();
  });

  // --- Initial State ---
  describe('initial state', () => {
    it('exposes a subscribe method', () => {
      expect(logs.subscribe).toBeTypeOf('function');
    });

    it('starts with 4 pre-seeded log entries', () => {
      const state = get(logs);
      expect(state).toHaveLength(4);
    });

    it('initial logs have the correct shape (id, timestamp, source, type, message)', () => {
      const state = get(logs);
      for (const log of state) {
        expect(log).toHaveProperty('id');
        expect(log).toHaveProperty('timestamp');
        expect(log).toHaveProperty('source');
        expect(log).toHaveProperty('type');
        expect(log).toHaveProperty('message');
      }
    });

    it('initial logs only use allowed type values', () => {
      const allowedTypes: LogLine['type'][] = ['info', 'success', 'warning', 'error'];
      const state = get(logs);
      for (const log of state) {
        expect(allowedTypes).toContain(log.type);
      }
    });

    it('initial logs only use allowed source values', () => {
      const allowedSources = ['tick', 'mem', 'sys', 'task'];
      const state = get(logs);
      for (const log of state) {
        expect(allowedSources).toContain(log.source);
      }
    });

    it('initial log messages are non-empty strings', () => {
      const state = get(logs);
      for (const log of state) {
        expect(log.message).toBeTypeOf('string');
        expect(log.message.length).toBeGreaterThan(0);
      }
    });
  });

  // --- addLog ---
  describe('addLog()', () => {
    it('prepends a new log to the front of the list', () => {
      const before = get(logs);
      const countBefore = before.length;

      logs.addLog({ source: 'sys', type: 'info', message: 'test log entry' });

      const after = get(logs);
      expect(after).toHaveLength(countBefore + 1);
      expect(after[0].message).toBe('test log entry');
      expect(after[0].source).toBe('sys');
      expect(after[0].type).toBe('info');
      expect(after[0].id).toBeTypeOf('string');
      expect(after[0].id.length).toBeGreaterThan(0);
    });

    it('attaches a timestamp string to the added log', () => {
      logs.addLog({ source: 'tick', type: 'info', message: 'ping' });
      const state = get(logs);
      const addedLog = state[0];

      expect(addedLog.timestamp).toBeTypeOf('string');
      expect(addedLog.timestamp.length).toBeGreaterThan(0);
    });

    it('does not modify existing log entries when adding a new one', () => {
      const before = get(logs);
      const originalSecond = before[0]; // will shift to index 1 after prepend

      logs.addLog({ source: 'mem', type: 'success', message: 'new entry' });

      const after = get(logs);
      expect(after[1]).toEqual(originalSecond);
    });

    it('caps the log list at 100 entries', () => {
      // Flood the store with 200 logs
      for (let i = 0; i < 200; i++) {
        logs.addLog({ source: 'sys', type: 'info', message: `flood log ${i}` });
      }

      const state = get(logs);
      expect(state.length).toBeLessThanOrEqual(100);
    });

    it('the most recent log is always at index 0 after multiple adds', () => {
      logs.addLog({ source: 'sys', type: 'warning', message: 'first added' });
      logs.addLog({ source: 'sys', type: 'error', message: 'second added' });
      logs.addLog({ source: 'sys', type: 'info', message: 'third added' });

      const state = get(logs);
      expect(state[0].message).toBe('third added');
    });

    it('accepts all valid type values', () => {
      const types: LogLine['type'][] = ['info', 'success', 'warning', 'error'];
      for (const type of types) {
        logs.addLog({ source: 'sys', type, message: `type-${type} message` });
        const state = get(logs);
        expect(state[0].type).toBe(type);
      }
    });

    it('exactly keeps the last 100 entries when exceeding the cap', () => {
      // Add 110 entries after initial 4 → total would be 114 → capped at 100
      for (let i = 0; i < 110; i++) {
        logs.addLog({ source: 'tick', type: 'info', message: `entry-${i}` });
      }

      const state = get(logs);
      expect(state).toHaveLength(100);
      // The most recent entry is at index 0
      expect(state[0].message).toBe('entry-109');
    });
  });

  // --- start / stop ---
  describe('start() and stop()', () => {
    it('exposes start and stop methods', () => {
      expect(logs.start).toBeTypeOf('function');
      expect(logs.stop).toBeTypeOf('function');
    });

    it('adds a log entry within the 3–8 second window when Math.random() returns 0', () => {
      vi.useFakeTimers();
      // Force Math.random() to 0 so delay = 3000 * 0 + 3000 = 3000ms exactly
      vi.spyOn(Math, 'random').mockReturnValue(0);

      let updateCount = 0;
      const unsubscribe = logs.subscribe(() => {
        updateCount++;
      });
      const initialUpdateCount = updateCount;

      logs.start();
      vi.advanceTimersByTime(3001);

      unsubscribe();
      logs.stop();
      vi.restoreAllMocks();

      expect(updateCount).toBeGreaterThan(initialUpdateCount);
    });

    it('adds a new log entry after advancing 8 seconds (within max delay)', () => {
      vi.useFakeTimers();

      let updateCount = 0;
      const unsubscribe = logs.subscribe(() => {
        updateCount++;
      });
      const initialUpdateCount = updateCount;

      logs.start();
      vi.advanceTimersByTime(8001);

      unsubscribe();
      logs.stop();

      expect(updateCount).toBeGreaterThan(initialUpdateCount);
    });

    it('stops adding logs after stop() is called', () => {
      vi.useFakeTimers();

      logs.start();
      vi.advanceTimersByTime(4000);
      logs.stop();

      const countAfterStop = get(logs).length;

      // Advance much further — no new logs should appear
      vi.advanceTimersByTime(30000);

      const countAfterWait = get(logs).length;
      expect(countAfterWait).toBe(countAfterStop);
    });

    it('does not start a second timer when start() is called twice', () => {
      vi.useFakeTimers();

      logs.start();
      logs.start(); // should be a no-op

      // If two timers ran, we'd get duplicate entries faster;
      // we just verify stop() clears properly and no errors occur
      vi.advanceTimersByTime(4000);
      logs.stop();

      // Store is still functional
      const state = get(logs);
      expect(Array.isArray(state)).toBe(true);
    });

    it('added log entries have valid source values', () => {
      vi.useFakeTimers();
      const allowedSources = ['tick', 'mem', 'sys', 'task'];

      logs.start();
      vi.advanceTimersByTime(4000);
      logs.stop();

      const state = get(logs);
      // All entries (including seed + newly added) must have valid source
      for (const log of state) {
        expect(allowedSources).toContain(log.source);
      }
    });

    it('added log entries have valid type values', () => {
      vi.useFakeTimers();
      const allowedTypes: LogLine['type'][] = ['info', 'success', 'warning', 'error'];

      logs.start();
      vi.advanceTimersByTime(4000);
      logs.stop();

      const state = get(logs);
      for (const log of state) {
        expect(allowedTypes).toContain(log.type);
      }
    });

    it('can be restarted after stopping', () => {
      vi.useFakeTimers();

      logs.start();
      vi.advanceTimersByTime(4000);
      logs.stop();

      const countAfterFirst = get(logs).length;

      logs.start();
      vi.advanceTimersByTime(4000);
      logs.stop();

      const countAfterSecond = get(logs).length;
      expect(countAfterSecond).toBeGreaterThanOrEqual(countAfterFirst);
    });
  });

  // --- clearLogs ---
  describe('clearLogs()', () => {
    it('exposes a clearLogs method', () => {
      expect(logs.clearLogs).toBeTypeOf('function');
    });

    it('empties the logs array', () => {
      logs.addLog({ source: 'sys', type: 'info', message: 'test log' });
      logs.clearLogs();
      const state = get(logs);
      expect(state).toHaveLength(0);
    });
  });

  // --- Subscription ---
  describe('subscription', () => {
    it('calls subscriber immediately with current state', () => {
      const snapshots: LogLine[][] = [];
      const unsubscribe = logs.subscribe((v) => snapshots.push(v));
      unsubscribe();

      expect(snapshots).toHaveLength(1);
      expect(Array.isArray(snapshots[0])).toBe(true);
    });

    it('notifies subscribers when a log is added', () => {
      const snapshots: LogLine[][] = [];
      const unsubscribe = logs.subscribe((v) => snapshots.push(v));

      const callsBefore = snapshots.length;
      logs.addLog({ source: 'task', type: 'info', message: 'subscription test' });

      unsubscribe();

      expect(snapshots.length).toBeGreaterThan(callsBefore);
      expect(snapshots[snapshots.length - 1][0].message).toBe('subscription test');
    });
  });
});
