import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import { logs, logsConnected } from '$lib/stores/logs';
import { createLogsClient } from './logsClient';

class MockEventSource {
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  static instances: MockEventSource[] = [];
  static last: MockEventSource | null = null;

  constructor(public url: string) {
    MockEventSource.instances.push(this);
    MockEventSource.last = this;
  }

  static reset() {
    MockEventSource.instances = [];
    MockEventSource.last = null;
  }
}

describe('createLogsClient', () => {
  beforeEach(() => {
    MockEventSource.reset();
    vi.stubGlobal('EventSource', MockEventSource as unknown as typeof EventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function lastEs(): MockEventSource {
    return MockEventSource.last!;
  }

  it('creates an EventSource pointed at /logs SSE endpoint', () => {
    const client = createLogsClient();
    client.connect();
    expect(lastEs()).toBeTruthy();
    expect(lastEs().url).toContain('/logs');
    client.disconnect();
  });

  it('sets connected to true on open', () => {
    const client = createLogsClient();
    client.connect();
    logs.setConnected(false);

    lastEs().onopen!();

    expect(get(logsConnected)).toBe(true);
    client.disconnect();
  });

  it('sets connected to false on error', () => {
    vi.useFakeTimers();
    const client = createLogsClient();
    client.connect();
    lastEs().onopen!();
    logs.setConnected(true);

    lastEs().onerror!();

    expect(get(logsConnected)).toBe(false);
    client.disconnect();
  });

  it('adds a log entry from a well-formed SSE message', () => {
    const client = createLogsClient();
    client.connect();

    const before = get(logs).length;

    lastEs().onmessage!({ data: '{"source":"tick","type":"info","message":"hello"}' });

    const state = get(logs);
    expect(state.length).toBeGreaterThan(before);
    expect(state[0].message).toBe('hello');
    expect(state[0].source).toBe('tick');
    expect(state[0].type).toBe('info');
    client.disconnect();
  });

  it('adds a fallback entry from a malformed SSE message', () => {
    const client = createLogsClient();
    client.connect();

    const before = get(logs).length;

    lastEs().onmessage!({ data: '{bad json}' });

    const state = get(logs);
    expect(state.length).toBeGreaterThan(before);
    expect(state[0].message).toBe('{bad json}');
    client.disconnect();
  });

  it('reconnects with exponential backoff after error', () => {
    vi.useFakeTimers();
    const client = createLogsClient();
    client.connect();

    const firstUrl = lastEs().url;
    lastEs().onerror!();

    vi.advanceTimersByTime(1999);
    expect(lastEs()).toBeTruthy();

    vi.advanceTimersByTime(2);

    expect(MockEventSource.instances.length).toBeGreaterThanOrEqual(2);
    expect(lastEs().url).toBe(firstUrl);

    client.disconnect();
  });

  it('does not reconnect after disconnect() even when reconnect is queued', () => {
    vi.useFakeTimers();
    const client = createLogsClient();
    client.connect();

    lastEs().onerror!();
    const instancesBeforeDisconnect = MockEventSource.instances.length;
    client.disconnect();

    vi.advanceTimersByTime(5000);

    expect(MockEventSource.instances.length).toBe(instancesBeforeDisconnect);
    expect(get(logsConnected)).toBe(false);
  });

  // --- Live → LogLine mapping ---
  describe('live → LogLine mapping', () => {
    it('preserves all four valid type values', () => {
      const client = createLogsClient();
      client.connect();

      for (const type of ['info', 'success', 'warning', 'error'] as const) {
        const before = get(logs).length;
        lastEs().onmessage!({
          data: JSON.stringify({ source: 'sys', type, message: `type-${type}` })
        });
        const state = get(logs);
        expect(state[0].type).toBe(type);
        expect(state.length).toBeGreaterThan(before);
      }

      client.disconnect();
    });

    it('defaults unknown type to info', () => {
      const client = createLogsClient();
      client.connect();

      lastEs().onmessage!({ data: '{"source":"sys","type":"debug","message":"x"}' });
      expect(get(logs)[0].type).toBe('info');
      client.disconnect();
    });

    it('defaults missing type to info', () => {
      const client = createLogsClient();
      client.connect();

      lastEs().onmessage!({ data: '{"source":"sys","message":"x"}' });
      expect(get(logs)[0].type).toBe('info');
      client.disconnect();
    });

    it('defaults missing source to sys', () => {
      const client = createLogsClient();
      client.connect();

      lastEs().onmessage!({ data: '{"type":"info","message":"x"}' });
      expect(get(logs)[0].source).toBe('sys');
      client.disconnect();
    });

    it('defaults null source to sys', () => {
      const client = createLogsClient();
      client.connect();

      lastEs().onmessage!({ data: '{"source":null,"type":"info","message":"x"}' });
      expect(get(logs)[0].source).toBe('sys');
      client.disconnect();
    });

    it('defaults missing message to the raw event data', () => {
      const client = createLogsClient();
      client.connect();

      const rawData = '{"source":"sys","type":"info"}';
      lastEs().onmessage!({ data: rawData });
      expect(get(logs)[0].message).toBe(rawData);
      client.disconnect();
    });

    it('defaults null message to the raw event data', () => {
      const client = createLogsClient();
      client.connect();

      const rawData = '{"source":"sys","type":"info","message":null}';
      lastEs().onmessage!({ data: rawData });
      expect(get(logs)[0].message).toBe(rawData);
      client.disconnect();
    });

    it('handles an empty object with all defaults', () => {
      const client = createLogsClient();
      client.connect();

      lastEs().onmessage!({ data: '{}' });
      const entry = get(logs)[0];
      expect(entry.source).toBe('sys');
      expect(entry.type).toBe('info');
      expect(entry.message).toBe('{}');
      client.disconnect();
    });

    it('entirely non-JSON payload falls back to info entry', () => {
      const client = createLogsClient();
      client.connect();

      lastEs().onmessage!({ data: '[1, 2, 3' });
      const entry = get(logs)[0];
      expect(entry.source).toBe('sys');
      expect(entry.type).toBe('info');
      expect(entry.message).toBe('[1, 2, 3');
      client.disconnect();
    });
  });
});
