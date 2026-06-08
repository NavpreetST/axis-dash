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

  it('does not reconnect after disconnect()', () => {
    vi.useFakeTimers();
    const client = createLogsClient();
    client.connect();

    const instancesBeforeDisconnect = MockEventSource.instances.length;
    client.disconnect();
    logs.setConnected(true);

    vi.advanceTimersByTime(5000);

    expect(MockEventSource.instances.length).toBe(instancesBeforeDisconnect);
    expect(get(logsConnected)).toBe(true);
  });
});
