import { writable } from 'svelte/store';

export interface Neurobus {
  reward: number;
  novelty: number;
  attention: number;
  patience: number;
  threat: number;
  trust: number;
}

export interface NeurobusHistory {
  reward: number[];
  novelty: number[];
  attention: number[];
  patience: number[];
  threat: number[];
  trust: number[];
}

export interface TelemetryData {
  uptime_seconds: number;
  tick_rate: number;
  pam: number;
  rpd_used: number;
  rpd_budget: number;
  provider: string;
  connected: boolean;
  neurobus: Neurobus;
  neurobusHistory: NeurobusHistory;
}

const initialData: TelemetryData = {
  uptime_seconds: 51742, // 14h 22m
  tick_rate: 9.8,
  pam: 0.91,
  rpd_used: 37,
  rpd_budget: 240,
  provider: 'gemini-2.5-flash',
  connected: true,
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
  }
};

const createTelemetryStore = () => {
  const { subscribe, update } = writable<TelemetryData>(initialData);
  let interval: ReturnType<typeof setInterval> | null = null;

  const start = () => {
    if (interval) return;
    interval = setInterval(() => {
      update((state) => {
        if (!state.connected) return state;

        // Simulate variation in data
        const nextUptime = state.uptime_seconds + 1;
        const nextTickRate = +(9.8 + (Math.random() - 0.5) * 0.4).toFixed(1);

        // Coherence (PAM) varies slowly
        const nextPam = +Math.max(
          0.75,
          Math.min(1.0, state.pam + (Math.random() - 0.5) * 0.02)
        ).toFixed(2);

        // Randomly update NeuroBus values slightly
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
          reward: [...state.neurobusHistory.reward, nextNeurobus.reward].slice(-60),
          novelty: [...state.neurobusHistory.novelty, nextNeurobus.novelty].slice(-60),
          attention: [...state.neurobusHistory.attention, nextNeurobus.attention].slice(-60),
          patience: [...state.neurobusHistory.patience, nextNeurobus.patience].slice(-60),
          threat: [...state.neurobusHistory.threat, nextNeurobus.threat].slice(-60),
          trust: [...state.neurobusHistory.trust, nextNeurobus.trust].slice(-60)
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

  return {
    subscribe,
    start,
    stop,
    toggleConnection
  };
};

export const telemetry = createTelemetryStore();
