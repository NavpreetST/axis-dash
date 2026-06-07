import { writable } from 'svelte/store';
import { config } from '$lib/config';

/** Scalar neurobus signal values (live bridge emits these as numbers per tick). */
export interface Neurobus {
  reward: number;
  novelty: number;
  attention: number;
  patience: number;
  threat: number;
  trust: number;
}

/** Frontend-only rolling history for sparkline rendering; capped at 60 entries per channel. */
export interface NeurobusHistory {
  reward: number[];
  novelty: number[];
  attention: number[];
  patience: number[];
  threat: number[];
  trust: number[];
}

/**
 * Full telemetry shape. Mirrors the live `/state` frame with two
 * extensions:
 * - `pam` is `number | null` because the bridge may emit null when PAM
 *   cannot be computed; the UI renders `--` instead of fabricating a value.
 * - `neurobusHistory` and `hidden_state` are frontend-only — the bridge
 *   does not send them.
 */
export interface TelemetryData {
  uptime_seconds: number;
  tick_rate: number;
  pam: number | null;
  rpd_used: number;
  rpd_budget: number;
  provider: string;
  connected: boolean;
  is_speaking: boolean;
  neurobus: Neurobus;
  neurobusHistory: NeurobusHistory;
  hidden_state: number[];
}

const NEUROBUS_KEYS = ['reward', 'novelty', 'attention', 'patience', 'threat', 'trust'] as const;

const initialData: TelemetryData = {
  uptime_seconds: 51742,
  tick_rate: 9.8,
  pam: 0.91,
  rpd_used: 37,
  rpd_budget: 240,
  provider: 'gemini-2.5-flash',
  connected: true,
  is_speaking: false,
  neurobus: {
    reward: 0.72,
    novelty: 0.45,
    attention: 0.88,
    patience: 0.65,
    threat: 0.08,
    trust: 0.92
  },
  neurobusHistory: {
    reward: [0.72],
    novelty: [0.45],
    attention: [0.88],
    patience: [0.65],
    threat: [0.08],
    trust: [0.92]
  },
  hidden_state: []
};

/**
 * Unknown/loading state used by the live bridge before the first frame
 * arrives. Keeps the UI on the existing `--` fallback instead of
 * flashing fabricated mock values.
 */
const unknownData: TelemetryData = {
  uptime_seconds: 0,
  tick_rate: 0,
  pam: null,
  rpd_used: 0,
  rpd_budget: 0,
  provider: '',
  connected: false,
  is_speaking: false,
  neurobus: {
    reward: 0,
    novelty: 0,
    attention: 0,
    patience: 0,
    threat: 0,
    trust: 0
  },
  neurobusHistory: {
    reward: [],
    novelty: [],
    attention: [],
    patience: [],
    threat: [],
    trust: []
  },
  hidden_state: []
};

const HISTORY_CAP = 60;

const createTelemetryStore = () => {
  const { subscribe, update, set } = writable<TelemetryData>(initialData);
  let interval: ReturnType<typeof setInterval> | null = null;

  const start = () => {
    if (interval) return;
    interval = setInterval(() => {
      update((state) => {
        if (!state.connected) return state;

        const nextUptime = state.uptime_seconds + 1;
        const nextTickRate = +(9.8 + (Math.random() - 0.5) * 0.4).toFixed(1);

        const basePam = state.pam ?? 0.9;
        const nextPam = +Math.max(
          0.75,
          Math.min(1.0, basePam + (Math.random() - 0.5) * 0.02)
        ).toFixed(2);

        const nextNeurobus = {
          reward: +Math.max(
            0,
            Math.min(1, state.neurobus.reward + (Math.random() - 0.5) * 0.05)
          ).toFixed(2),
          novelty: +Math.max(
            0,
            Math.min(1, state.neurobus.novelty + (Math.random() - 0.5) * 0.03)
          ).toFixed(2),
          attention: +Math.max(
            0,
            Math.min(1, state.neurobus.attention + (Math.random() - 0.5) * 0.02)
          ).toFixed(2),
          patience: +Math.max(
            0,
            Math.min(1, state.neurobus.patience + (Math.random() - 0.5) * 0.04)
          ).toFixed(2),
          threat: +Math.max(
            0,
            Math.min(1, state.neurobus.threat + (Math.random() - 0.5) * 0.01)
          ).toFixed(2),
          trust: +Math.max(
            0,
            Math.min(1, state.neurobus.trust + (Math.random() - 0.5) * 0.03)
          ).toFixed(2)
        };

        const nextNeurobusHistory = {
          reward: [...state.neurobusHistory.reward, nextNeurobus.reward].slice(-HISTORY_CAP),
          novelty: [...state.neurobusHistory.novelty, nextNeurobus.novelty].slice(-HISTORY_CAP),
          attention: [...state.neurobusHistory.attention, nextNeurobus.attention].slice(
            -HISTORY_CAP
          ),
          patience: [...state.neurobusHistory.patience, nextNeurobus.patience].slice(-HISTORY_CAP),
          threat: [...state.neurobusHistory.threat, nextNeurobus.threat].slice(-HISTORY_CAP),
          trust: [...state.neurobusHistory.trust, nextNeurobus.trust].slice(-HISTORY_CAP)
        };

        return {
          ...state,
          uptime_seconds: nextUptime,
          tick_rate: nextTickRate,
          pam: nextPam,
          neurobus: nextNeurobus,
          neurobusHistory: nextNeurobusHistory
        };
      });
    }, 1000);
  };

  const stop = () => {
    if (interval) {
      clearInterval(interval);
      interval = null;
    }
  };

  const toggleConnection = () => {
    update((state) => {
      const nextConnected = !state.connected;
      return {
        ...state,
        connected: nextConnected
      };
    });
  };

  /**
   * Merge a partial frame from the live `/state` stream into the store.
   *
   * Only keys present on the incoming `frame` are applied; missing keys
   * keep their previous value. For `neurobus`, history is only appended
   * for channels that the incoming frame actually provided — we do not
   * re-append the existing scalar just because `frame.neurobus` was
   * omitted entirely. Each history array is capped at 60 entries.
   */
  const applyLiveFrame = (frame: Partial<TelemetryData>) => {
    update((state) => {
      const nextNeurobus: Neurobus = frame.neurobus
        ? { ...state.neurobus, ...frame.neurobus }
        : state.neurobus;
      const nextHistory: NeurobusHistory = { ...state.neurobusHistory };
      if (frame.neurobus) {
        for (const key of NEUROBUS_KEYS) {
          const incoming = frame.neurobus[key];
          if (typeof incoming === 'number') {
            nextHistory[key] = [...nextHistory[key], incoming].slice(-HISTORY_CAP);
          }
        }
      }
      return {
        ...state,
        // `connected` is owned by the WebSocket lifecycle (onopen/onclose)
        // and is intentionally NOT overridden by frame data — the bridge
        // sends `connected: false` to signal daemon health (e.g. its
        // upstream data source is down), which is a different concept
        // from the transport being open. Letting the frame flip the flag
        // makes the UI flip to `--` even though frames are still flowing.
        uptime_seconds: frame.uptime_seconds ?? state.uptime_seconds,
        tick_rate: frame.tick_rate ?? state.tick_rate,
        pam: frame.pam !== undefined ? frame.pam : state.pam,
        rpd_used: frame.rpd_used ?? state.rpd_used,
        rpd_budget: frame.rpd_budget ?? state.rpd_budget,
        provider: frame.provider ?? state.provider,
        is_speaking: frame.is_speaking ?? state.is_speaking,
        neurobus: nextNeurobus,
        neurobusHistory: nextHistory,
        hidden_state: frame.hidden_state ?? state.hidden_state
      };
    });
  };

  /**
   * Force the store into the unknown/loading snapshot. Called by the
   * live bridge on mount so the UI shows `--` placeholders instead of
   * the seeded mock values before the first `/state` frame arrives.
   */
  const resetToUnknown = () => {
    set({ ...unknownData });
  };

  /**
   * Directly set the `connected` flag. The state WS client calls this
   * on socket open/close so the UI mirrors the real connection state.
   */
  const setConnected = (connected: boolean) => {
    update((state) => ({ ...state, connected }));
  };

  return {
    subscribe,
    start,
    stop,
    toggleConnection,
    applyLiveFrame,
    resetToUnknown,
    setConnected,
    isLiveMode: () => config.useLiveBridge
  };
};

/**
 * Shared telemetry store. Mock mode (`PUBLIC_USE_LIVE_BRIDGE=false`)
 * drives it via the internal 1s interval; live mode drives it from the
 * `/state` WebSocket frames.
 */
export const telemetry = createTelemetryStore();
