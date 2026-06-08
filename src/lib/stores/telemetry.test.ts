import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
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

      expect(state.neurobusHistory.reward).toEqual([0.72]);
      expect(state.neurobusHistory.novelty).toEqual([0.45]);
      expect(state.neurobusHistory.attention).toEqual([0.88]);
      expect(state.neurobusHistory.patience).toEqual([0.65]);
      expect(state.neurobusHistory.threat).toEqual([0.08]);
      expect(state.neurobusHistory.trust).toEqual([0.92]);
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

    it('keeps all neurobus values within [0, 1] across many ticks and caps history to 60', () => {
      vi.useFakeTimers();

      telemetry.start();
      for (let i = 0; i < 200; i++) {
        vi.advanceTimersByTime(1000);
        const { neurobus, neurobusHistory } = get(telemetry);
        const keys = Object.keys(neurobus) as (keyof Neurobus)[];
        for (const key of keys) {
          expect(neurobus[key]).toBeGreaterThanOrEqual(0);
          expect(neurobus[key]).toBeLessThanOrEqual(1);

          const len = neurobusHistory[key].length;
          expect(len).toBeLessThanOrEqual(60);
          if (i >= 59) expect(len).toBe(60);
          expect(neurobusHistory[key][len - 1]).toBe(neurobus[key]);
        }
      }

      // Bounds check the full captured history once. The per-tick loop
      // already proves the most recent sample is in range and the cap
      // is enforced; this final sweep proves every recorded value is in
      // [0, 1] without paying for ~72k `expect()` calls inside the hot
      // 200-tick loop.
      const { neurobusHistory } = get(telemetry);
      for (const key of Object.keys(neurobusHistory) as (keyof Neurobus)[]) {
        for (const val of neurobusHistory[key]) {
          expect(val).toBeGreaterThanOrEqual(0);
          expect(val).toBeLessThanOrEqual(1);
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

    it('all neurobus values are numbers and history values are arrays of numbers', () => {
      const { neurobus, neurobusHistory } = get(telemetry);
      for (const val of Object.values(neurobus)) {
        expect(val).toBeTypeOf('number');
      }
      for (const historyArr of Object.values(neurobusHistory)) {
        expect(historyArr).toBeInstanceOf(Array);
        for (const val of historyArr) {
          expect(val).toBeTypeOf('number');
        }
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
      expect(state).toHaveProperty('neurobusHistory');
    });
  });

  // --- Live bridge contract ---
  // The Helios /state WebSocket sends a 14-field JSON frame on every
  // tick. These tests pin the dashboard-side parsing contract so the
  // three nuances called out in the contract doc stay correct:
  //   1. `connected: false` at idle is expected (the renderer only
  //      writes on chat turns, so the daemon-state file is stale when
  //      no turn is in flight). The transport is still healthy. The
  //      dashboard MUST key liveness off the WS lifecycle, not the
  //      frame's `connected` field.
  //   2. `pam` is hardcoded null on the wire — the bridge has no
  //      runtime source for it. The store MUST preserve null (not
  //      coerce to 0 or `undefined`) so the UI renders `--`.
  //   3. `tick_id` is always 0 and `tick_rate` is the documented
  //      constant 1.0. The store accepts them as plain numbers; no
  //      special-casing is required, but the contract test pins the
  //      shape so a future bridge change surfaces as a test diff.
  describe('live /state frame contract', () => {
    // A representative frame shape matching what the live Helios
    // bridge emits. Includes every field the store consumes, plus the
    // two extra fields the bridge sends that the store intentionally
    // does not model (`tick_id`, `last_action_type`).
    const liveFrame: Partial<TelemetryData> = {
      uptime_seconds: 75114,
      tick_rate: 1.0,
      pam: null,
      rpd_used: 18,
      rpd_budget: 240,
      provider: 'gemini',
      connected: false,
      is_speaking: false,
      neurobus: {
        reward: 0.42,
        novelty: 0.31,
        attention: 0.55,
        patience: 0.61,
        threat: 0.05,
        trust: 0.78
      }
    };

    beforeEach(() => {
      // Start each contract test from the unknown snapshot so prior
      // mock-mode ticks don't pollute the assertions. We don't go
      // through `start()` here because the contract tests are about
      // pure `applyLiveFrame` semantics, not the interval.
      telemetry.resetToUnknown();
    });

    it('applies every known field from a live frame', () => {
      telemetry.applyLiveFrame(liveFrame);
      const s = get(telemetry);
      expect(s.uptime_seconds).toBe(75114);
      expect(s.tick_rate).toBe(1.0);
      expect(s.pam).toBeNull();
      expect(s.rpd_used).toBe(18);
      expect(s.rpd_budget).toBe(240);
      expect(s.provider).toBe('gemini');
      expect(s.is_speaking).toBe(false);
      expect(s.neurobus).toEqual(liveFrame.neurobus);
    });

    it('appends to neurobus history for every channel present in the frame', () => {
      telemetry.applyLiveFrame(liveFrame);
      const s = get(telemetry);
      for (const key of Object.keys(s.neurobus) as (keyof Neurobus)[]) {
        expect(s.neurobusHistory[key]).toEqual([liveFrame.neurobus![key]]);
      }
    });

    it('ignores unknown / future bridge fields without throwing', () => {
      // Bridge may add fields the store hasn't modelled yet. The
      // store must accept the frame and not crash on unknown keys.
      expect(() => {
        telemetry.applyLiveFrame({
          ...liveFrame,
          tick_id: 0,
          last_action_type: 'idle',
          mnemosyne_event: null,
          h: [0.0, 0.0, 0.5]
        } as Partial<TelemetryData>);
      }).not.toThrow();
      // Sanity: known fields still landed.
      const s = get(telemetry);
      expect(s.uptime_seconds).toBe(75114);
    });

    it('keeps a missing field at its previous value (no overwrite with undefined)', () => {
      telemetry.applyLiveFrame(liveFrame);
      const after = get(telemetry);
      telemetry.applyLiveFrame({ uptime_seconds: 99999 }); // only uptime
      const s = get(telemetry);
      expect(s.uptime_seconds).toBe(99999);
      expect(s.tick_rate).toBe(after.tick_rate);
      expect(s.pam).toBeNull();
      expect(s.rpd_used).toBe(18);
      expect(s.rpd_budget).toBe(240);
      expect(s.provider).toBe('gemini');
    });

    it('accepts tick_id / tick_rate of their documented contract values', () => {
      // tick_id is always 0, tick_rate is always 1.0 — pinned here so
      // any future bridge change is a deliberate test update.
      const frame1 = { ...liveFrame, tick_id: 0, tick_rate: 1.0 };
      telemetry.applyLiveFrame(frame1 as Partial<TelemetryData>);
      expect(get(telemetry).tick_rate).toBe(1.0);

      const frame2 = { ...liveFrame, tick_id: 0, tick_rate: 1.0 };
      telemetry.applyLiveFrame(frame2 as Partial<TelemetryData>);
      expect(get(telemetry).tick_rate).toBe(1.0);
    });
  });

  // --- Freshness / connected guard ---
  // The frame's `connected` field is daemon-health metadata: the
  // Helios renderer only writes the daemon-state file on chat
  // turns, so when no turn is in flight the field is `false` even
  // though the bridge WebSocket itself is fully open. The dashboard
  // would flicker every frame between `--` and the real values if
  // we let the frame flip `state.connected`. The WS lifecycle
  // (`onopen` / `onclose`) is the sole owner of that flag.
  describe('freshness / connected guard', () => {
    it('does NOT let a frame with connected:false flip the store flag while the WS is open', () => {
      // Simulate the WS having just opened.
      telemetry.setConnected(true);
      expect(get(telemetry).connected).toBe(true);

      // Bridge sends a frame with connected:false (renderer idle,
      // no chat turn in flight). The store MUST keep `connected: true`
      // because the transport is healthy.
      telemetry.applyLiveFrame({
        uptime_seconds: 100,
        tick_rate: 1.0,
        pam: null,
        connected: false
      });

      expect(get(telemetry).connected).toBe(true);
    });

    it('does NOT let a frame with connected:true revive a closed WS', () => {
      // Simulate the WS having just closed.
      telemetry.setConnected(false);
      expect(get(telemetry).connected).toBe(false);

      // A frame arriving during a reconnect attempt (race: in-flight
      // from before the close) MUST NOT mark us as connected. Only
      // `setConnected(true)` — called from `ws.onopen` — can do that.
      telemetry.applyLiveFrame({
        uptime_seconds: 200,
        tick_rate: 1.0,
        pam: null,
        connected: true
      });

      expect(get(telemetry).connected).toBe(false);
    });

    it('preserves the connected flag through many frames with mixed values', () => {
      telemetry.setConnected(true);
      for (let i = 0; i < 20; i++) {
        telemetry.applyLiveFrame({
          uptime_seconds: 1000 + i,
          tick_rate: 1.0,
          pam: null,
          connected: i % 2 === 0 // alternates, but the WS is "open"
        });
      }
      expect(get(telemetry).connected).toBe(true);
      expect(get(telemetry).uptime_seconds).toBe(1019);
    });
  });

  // --- pam:null invariant ---
  // `pam` is hardcoded null on the wire — the bridge has no runtime
  // source for it (per the Helios contract doc). The store must
  // preserve null (not coerce to 0 or `undefined`) and the UI
  // renders `--` for null. Without this invariant, the KPI strip
  // would either show a fake `0.00` (misleading) or crash the
  // `pamThreshold` color function.
  describe('pam:null invariant', () => {
    it('preserves an explicit null pam from the frame', () => {
      telemetry.resetToUnknown();
      expect(get(telemetry).pam).toBeNull();
      telemetry.applyLiveFrame({ uptime_seconds: 100, tick_rate: 1.0, pam: null });
      expect(get(telemetry).pam).toBeNull();
    });

    it('keeps the previous pam value when the frame omits the field', () => {
      telemetry.resetToUnknown();
      telemetry.applyLiveFrame({ uptime_seconds: 100, tick_rate: 1.0, pam: 0.91 });
      expect(get(telemetry).pam).toBe(0.91);
      telemetry.applyLiveFrame({ uptime_seconds: 200, tick_rate: 1.0 }); // no pam
      expect(get(telemetry).pam).toBe(0.91);
    });

    it('treats pam:0 as a real value, not a missing value', () => {
      telemetry.resetToUnknown();
      telemetry.applyLiveFrame({ uptime_seconds: 100, tick_rate: 1.0, pam: 0 });
      expect(get(telemetry).pam).toBe(0);
      // 0 is a valid PAM reading; it is NOT null and the UI must
      // render `0.00`, not `--`. This guards against an over-eager
      // truthiness check (`frame.pam || state.pam`) that would lose it.
    });

    it('round-trips a sequence of (real, null, real, omitted) without losing values', () => {
      telemetry.resetToUnknown();
      telemetry.applyLiveFrame({ uptime_seconds: 1, tick_rate: 1.0, pam: 0.42 });
      expect(get(telemetry).pam).toBe(0.42);
      telemetry.applyLiveFrame({ uptime_seconds: 2, tick_rate: 1.0, pam: null });
      expect(get(telemetry).pam).toBeNull();
      telemetry.applyLiveFrame({ uptime_seconds: 3, tick_rate: 1.0, pam: 0.55 });
      expect(get(telemetry).pam).toBe(0.55);
      telemetry.applyLiveFrame({ uptime_seconds: 4, tick_rate: 1.0 }); // omitted
      expect(get(telemetry).pam).toBe(0.55);
    });
  });

  // --- Runtime block parsing ---
  // The bridge emits an additive `runtime` block with metadata about
  // the daemon's runtime environment. All sub-fields are optional —
  // the contract is the 14 top-level telemetry fields; `runtime` is
  // informational only. The store must preserve partial updates and
  // never fabricate missing values.
  describe('runtime block parsing', () => {
    beforeEach(() => {
      telemetry.resetToUnknown();
    });

    it('stores a full runtime block from a live frame', () => {
      const fullRuntime = {
        commit: 'abc123def',
        socket_path: '/var/run/helios.sock',
        launch_method: 'systemd',
        renderer_chain: 'aegis->orchestrator',
        memory_backend: 'lmdb',
        ncp: 4,
        budget: '12h',
        known_issues: ['issue-1', 'issue-2']
      };
      telemetry.applyLiveFrame({ uptime_seconds: 100, tick_rate: 1.0, runtime: fullRuntime });
      const s = get(telemetry);
      expect(s.runtime).toEqual(fullRuntime);
    });

    it('merges partial runtime updates without dropping prior values', () => {
      telemetry.applyLiveFrame({
        uptime_seconds: 100,
        tick_rate: 1.0,
        runtime: { commit: 'abc123', socket_path: '/run/helios.sock' }
      });
      telemetry.applyLiveFrame({
        uptime_seconds: 200,
        tick_rate: 1.0,
        runtime: { ncp: 8, budget: '24h' }
      });
      const s = get(telemetry);
      expect(s.runtime).toEqual({
        commit: 'abc123',
        socket_path: '/run/helios.sock',
        ncp: 8,
        budget: '24h'
      });
    });

    it('preserves prior runtime when frame omits it', () => {
      telemetry.applyLiveFrame({
        uptime_seconds: 100,
        tick_rate: 1.0,
        runtime: { commit: 'abc123' }
      });
      telemetry.applyLiveFrame({ uptime_seconds: 200, tick_rate: 1.0 });
      expect(get(telemetry).runtime).toEqual({ commit: 'abc123' });
    });

    it('renders -- for missing/null sub-fields in the UI', () => {
      telemetry.applyLiveFrame({
        uptime_seconds: 100,
        tick_rate: 1.0,
        runtime: { commit: 'abc123', socket_path: null, known_issues: [] }
      });
      const s = get(telemetry);
      expect(s.runtime?.commit).toBe('abc123');
      expect(s.runtime?.socket_path).toBeNull();
      expect(s.runtime?.known_issues).toEqual([]);
    });

    it('accepts string or number for ncp/budget fields', () => {
      telemetry.applyLiveFrame({
        uptime_seconds: 100,
        tick_rate: 1.0,
        runtime: { ncp: 'auto', budget: 48 }
      });
      const s = get(telemetry);
      expect(s.runtime?.ncp).toBe('auto');
      expect(s.runtime?.budget).toBe(48);
    });
  });
});
