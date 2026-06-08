import { describe, it, expect, vi, afterEach } from 'vitest';
import { toActivityItems } from './activityView.js';
import type { LogLine } from '$lib/stores/logs';

const mk = (overrides: Partial<LogLine> = {}): LogLine => ({
  id: 'log-1',
  timestamp: '14:22:08',
  source: 'tick',
  type: 'info',
  message: 'orb pulse ok',
  ...overrides
});

describe('toActivityItems', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns an empty array for empty input', () => {
    expect(toActivityItems([])).toEqual([]);
  });

  it('formats each log line into an ActivityItem', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-08T14:22:08'));

    const items = toActivityItems([mk()]);
    expect(items).toHaveLength(1);
    expect(items[0].key).toBe('log-1');
    expect(items[0].source).toBe('tick');
    expect(items[0].type).toBe('info');
    expect(items[0].message).toBe('orb pulse ok');
    expect(items[0].time).toBe('just now');
  });

  it('preserves all log types', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-08T14:22:08'));

    const types: LogLine['type'][] = ['info', 'success', 'warning', 'error'];
    const logs = types.map((t, i) => mk({ id: `l-${i}`, type: t, timestamp: '14:22:08' }));
    const items = toActivityItems(logs);
    expect(items.map((i) => i.type)).toEqual(types);
  });

  it('tolerates malformed log lines — missing id', () => {
    const log = mk({ id: '' as unknown as string });
    const items = toActivityItems([log]);
    expect(items).toHaveLength(1);
    expect(items[0].key).toMatch(/^act-/);
  });

  it('tolerates malformed log lines — missing timestamp', () => {
    const log = mk({ timestamp: '' });
    const items = toActivityItems([log]);
    expect(items).toHaveLength(1);
    expect(items[0].time).toBe('just now');
  });

  it('tolerates malformed log lines — missing message', () => {
    const log = mk({ message: '' as unknown as string });
    const items = toActivityItems([log]);
    expect(items).toHaveLength(1);
    expect(items[0].message).toBe('');
  });

  it('tolerates malformed log lines — invalid type falls back to info', () => {
    const log = mk({ type: 'critical' as LogLine['type'] });
    const items = toActivityItems([log]);
    expect(items).toHaveLength(1);
    expect(items[0].type).toBe('info');
  });

  it('preserves source even when empty', () => {
    const log = mk({ source: '' });
    const items = toActivityItems([log]);
    expect(items).toHaveLength(1);
    expect(items[0].source).toBe('');
  });

  it('formats relative time for recent entries', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-08T14:22:08'));

    const log = mk({ timestamp: '14:22:08' });
    const items = toActivityItems([log]);
    expect(items[0].time).toBe('just now');
  });

  it('shows "Xs ago" for entries less than 60s old', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-08T14:22:08'));

    const log = mk({ timestamp: '14:22:00' });
    const items = toActivityItems([log]);
    expect(items[0].time).toBe('8s ago');
  });

  it('shows "Xm ago" for entries at least 60s old', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-08T14:22:08'));

    const log = mk({ timestamp: '14:21:08' });
    const items = toActivityItems([log]);
    expect(items[0].time).toBe('1m ago');
  });

  it('shows "Xm ago" for entries within 5 minutes', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-08T14:22:08'));

    const log = mk({ timestamp: '14:19:08' });
    const items = toActivityItems([log]);
    expect(items[0].time).toBe('3m ago');
  });

  it('generates unique deterministic keys for colliding fallback ids', () => {
    const logs = [
      mk({
        id: '' as unknown as string,
        timestamp: '14:22:00',
        source: 'tick',
        type: 'info',
        message: 'event'
      }),
      mk({
        id: '' as unknown as string,
        timestamp: '14:22:00',
        source: 'tick',
        type: 'info',
        message: 'event'
      }),
      mk({
        id: '' as unknown as string,
        timestamp: '14:22:00',
        source: 'tick',
        type: 'info',
        message: 'event'
      })
    ];
    const items = toActivityItems(logs);
    expect(items).toHaveLength(3);
    const keys = items.map((i) => i.key);
    expect(new Set(keys).size).toBe(3);
    expect(keys[0]).toMatch(/^act-/);
    expect(keys[1]).toMatch(/^act-.+-2$/);
    expect(keys[2]).toMatch(/^act-.+-3$/);
  });
});
