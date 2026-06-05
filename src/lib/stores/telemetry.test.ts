import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';

// Re-import the factory so each test gets a fresh store instance
// We do this by importing a local factory version

// Since createTelemetryStore is not exported, we import the exported singleton
// and reset via the start/stop API. For isolation, we test observable behaviors.
import { telemetry, type TelemetryData, type Neurobus } from './telemetry.js';

describe('telemetry store', () => {
  afterEach(() => {
    // Always stop the interval to prevent timer leaks between tests
    telemetry.stop();
    vi.useRealTimers();
  });

  // --- Initial State ---
  describe('initial state', () => {
    it('exposes a subscribe method', () => {
      expect(telemetry.subscribe).toBeTypeOf('function');
    });

    it('has the correct initial uptime_seconds', () => {
      const state = get(telemetry);
      expect(state.uptime_seconds).toBe(51742);
    });

    it('has the correct initial tick_rate', () => {
      const state = get(telemetry);
      expect(state.tick_rate).toBe(9.8);
    });

    it('has the correct initial pam value', () => {
      const state = get(telemetry);
      expect(state.pam).toBe(0.91);
    });

    it('has the correct initial rpd_used', () => {
      const state = get(telemetry);
      expect(state.rpd_used).toBe(37);
    });

    it('has the correct initial rpd_budget', () => {
      const state = get(telemetry);
      expect(state.rpd_budget).toBe(240);
    });

    it('has the correct initial provider', () => {
      const state = get(telemetry);
      expect(state.provider).toBe('gemini-2.5-flash');
    });

    it('starts in connected state', () => {
      const state = get(telemetry);
      expect(state.connected).toBe(true);
    });

    it('has the correct initial neurobus values', () => {
      const state = get(telemetry);
      expect(state.neurobus.reward).toBe(0.72);
      expect(state.neurobus.novelty).toBe(0.45);
      expect(state.neurobus.attention).toBe(0.88);
      expect(state.neurobus.patience).toBe(0.65);
      expect(state.neurobus.threat).toBe(0.08);
      expect(state.neurobus.trust).toBe(0.92);
    });
  });

  // --- toggleConnection ---
  describe('toggleConnection()', () => {
    it('toggles connected from true to false', () => {
      // Ensure we start connected
      const before = get(telemetry);
      const wasConnected = before.connected;

      telemetry.toggleConnection();
      const after = get(telemetry);
      expect(after.connected).toBe(!wasConnected);

      // Always restore to original state
      telemetry.toggleConnection();
    });

    it('toggles connected back to true on second call', () => {
      const before = get(telemetry);
      const wasConnected = before.connected;

      telemetry.toggleConnection();
      telemetry.toggleConnection();

      const after = get(telemetry);
      expect(after.connected).toBe(wasConnected);
    });

    it('preserves all other state fields when toggling connection', () => {
      const before = get(telemetry);
      telemetry.toggleConnection();
      const after = get(telemetry);

      expect(after.uptime_seconds).toBe(before.uptime_seconds);
      expect(after.tick_rate).toBe(before.tick_rate);
      expect(after.pam).toBe(before.pam);
      expect(after.rpd_used).toBe(before.rpd_used);
      expect(after.rpd_budget).toBe(before.rpd_budget);
      expect(after.provider).toBe(before.provider);
      expect(after.neurobus).toEqual(before.neurobus);

      // Restore
      telemetry.toggleConnection();
    });
  });

  // --- start / stop ---
  describe('start() and stop()', () => {
    it('exposes start and stop methods', () => {
      expect(telemetry.start).toBeTypeOf('function');
      expect(telemetry.stop).toBeTypeOf('function');
    });

    it('increments uptime_seconds by 1 after each 1000ms tick', () => {
      vi.useFakeTimers();
      const initialUptime = get(telemetry).uptime_seconds;

      telemetry.start();
      vi.advanceTimersByTime(1000);

      const state = get(telemetry);
      expect(state.uptime_seconds).toBe(initialUptime + 1);

      telemetry.stop();
    });

    it('increments uptime_seconds by 3 after three 1000ms ticks', () => {
      vi.useFakeTimers();
      const initialUptime = get(telemetry).uptime_seconds;

      telemetry.start();
      vi.advanceTimersByTime(3000);

      const state = get(telemetry);
      expect(state.uptime_seconds).toBe(initialUptime + 3);

      telemetry.stop();
    });

    it('does not start a second interval when start() is called twice', () => {
      vi.useFakeTimers();
      const initialUptime = get(telemetry).uptime_seconds;

      telemetry.start();
      telemetry.start(); // second call should be a no-op
      vi.advanceTimersByTime(1000);

      // Should only have incremented once (one interval, not two)
      const state = get(telemetry);
      expect(state.uptime_seconds).toBe(initialUptime + 1);

      telemetry.stop();
    });

    it('stops updating after stop() is called', () => {
      vi.useFakeTimers();

      telemetry.start();
      vi.advanceTimersByTime(1000);
      const uptimeAfterOneTick = get(telemetry).uptime_seconds;

      telemetry.stop();
      vi.advanceTimersByTime(2000);

      // Should not have incremented further
      const state = get(telemetry);
      expect(state.uptime_seconds).toBe(uptimeAfterOneTick);
    });

    it('does not update state when connected is false', () => {
      vi.useFakeTimers();

      // Disconnect
      const wasConnected = get(telemetry).connected;
      if (wasConnected) {
        telemetry.toggleConnection(); // set to false
      }

      const uptimeBefore = get(telemetry).uptime_seconds;

      telemetry.start();
      vi.advanceTimersByTime(1000);

      const state = get(telemetry);
      expect(state.uptime_seconds).toBe(uptimeBefore);

      telemetry.stop();

      // Restore connection
      if (wasConnected) {
        telemetry.toggleConnection();
      }
    });

    it('keeps tick_rate within valid range [9.6, 10.0] after ticks', () => {
      vi.useFakeTimers();

      telemetry.start();
      // Run many ticks to check bounds
      for (let i = 0; i < 100; i++) {
        vi.advanceTimersByTime(1000);
        const state = get(telemetry);
        // tick_rate = 9.8 ± 0.2 (random * 0.4 - 0.2)
        expect(state.tick_rate).toBeGreaterThanOrEqual(9.6);
        expect(state.tick_rate).toBeLessThanOrEqual(10.0);
      }

      telemetry.stop();
    });

    it('keeps pam within [0.75, 1.0] across many ticks', () => {
      vi.useFakeTimers();

      telemetry.start();
      for (let i = 0; i < 200; i++) {
        vi.advanceTimersByTime(1000);
        const state = get(telemetry);
        expect(state.pam).toBeGreaterThanOrEqual(0.75);
        expect(state.pam).toBeLessThanOrEqual(1.0);
      }

      telemetry.stop();
    });

    it('keeps all neurobus values within [0, 1] across many ticks', () => {
      vi.useFakeTimers();

      telemetry.start();
      for (let i = 0; i < 200; i++) {
        vi.advanceTimersByTime(1000);
        const { neurobus } = get(telemetry);
        const keys = Object.keys(neurobus) as (keyof Neurobus)[];
        for (const key of keys) {
          expect(neurobus[key]).toBeGreaterThanOrEqual(0);
          expect(neurobus[key]).toBeLessThanOrEqual(1);
        }
      }

      telemetry.stop();
    });

    it('does not modify rpd_used or rpd_budget during simulation', () => {
      vi.useFakeTimers();

      const initialRpdUsed = get(telemetry).rpd_used;
      const initialRpdBudget = get(telemetry).rpd_budget;

      telemetry.start();
      vi.advanceTimersByTime(5000);

      const state = get(telemetry);
      expect(state.rpd_used).toBe(initialRpdUsed);
      expect(state.rpd_budget).toBe(initialRpdBudget);

      telemetry.stop();
    });

    it('does not modify provider during simulation', () => {
      vi.useFakeTimers();

      const initialProvider = get(telemetry).provider;

      telemetry.start();
      vi.advanceTimersByTime(5000);

      const state = get(telemetry);
      expect(state.provider).toBe(initialProvider);

      telemetry.stop();
    });

    it('can be restarted after stopping', () => {
      vi.useFakeTimers();

      const initialUptime = get(telemetry).uptime_seconds;

      telemetry.start();
      vi.advanceTimersByTime(1000);
      telemetry.stop();

      const uptimeAfterFirstRun = get(telemetry).uptime_seconds;
      expect(uptimeAfterFirstRun).toBe(initialUptime + 1);

      telemetry.start();
      vi.advanceTimersByTime(1000);
      telemetry.stop();

      const uptimeAfterRestart = get(telemetry).uptime_seconds;
      expect(uptimeAfterRestart).toBe(initialUptime + 2);
    });
  });

  // --- Subscription ---
  describe('subscription', () => {
    it('calls subscriber immediately with current state', () => {
      const values: TelemetryData[] = [];
      const unsubscribe = telemetry.subscribe((v) => values.push(v));
      unsubscribe();

      expect(values).toHaveLength(1);
      expect(values[0].uptime_seconds).toBeTypeOf('number');
    });

    it('notifies subscribers when connection is toggled', () => {
      const values: boolean[] = [];
      const unsubscribe = telemetry.subscribe((v) => values.push(v.connected));

      const callsBefore = values.length;
      telemetry.toggleConnection();
      telemetry.toggleConnection();

      unsubscribe();

      expect(values.length).toBeGreaterThan(callsBefore);
      // After two toggles we're back to the original state
      expect(values[values.length - 1]).toBe(values[0]);
    });
  });

  // --- Type Interface ---
  describe('TelemetryData and Neurobus interface shapes', () => {
    it('neurobus object has all required keys', () => {
      const { neurobus } = get(telemetry);
      expect(neurobus).toHaveProperty('reward');
      expect(neurobus).toHaveProperty('novelty');
      expect(neurobus).toHaveProperty('attention');
      expect(neurobus).toHaveProperty('patience');
      expect(neurobus).toHaveProperty('threat');
      expect(neurobus).toHaveProperty('trust');
    });

    it('all neurobus values are numbers', () => {
      const { neurobus } = get(telemetry);
      for (const val of Object.values(neurobus)) {
        expect(val).toBeTypeOf('number');
      }
    });

    it('TelemetryData has all required top-level fields', () => {
      const state = get(telemetry);
      expect(state).toHaveProperty('uptime_seconds');
      expect(state).toHaveProperty('tick_rate');
      expect(state).toHaveProperty('pam');
      expect(state).toHaveProperty('rpd_used');
      expect(state).toHaveProperty('rpd_budget');
      expect(state).toHaveProperty('provider');
      expect(state).toHaveProperty('connected');
      expect(state).toHaveProperty('neurobus');
    });
  });
});