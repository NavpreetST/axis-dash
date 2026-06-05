import { writable } from 'svelte/store';

export interface Neurobus {
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

        // Randomly update NeuroBus values slightly and maintain a rolling 60s history
        const getNextVal = (currentHistory: number[], step: number): number => {
          const lastVal = currentHistory[currentHistory.length - 1];
          return +Math.max(0, Math.min(1, lastVal + (Math.random() - 0.5) * step)).toFixed(2);
        };

        const nextNeurobus = {
          reward: [...state.neurobus.reward, getNextVal(state.neurobus.reward, 0.05)].slice(-60),
          novelty: [...state.neurobus.novelty, getNextVal(state.neurobus.novelty, 0.03)].slice(-60),
          attention: [
            ...state.neurobus.attention,
            getNextVal(state.neurobus.attention, 0.02)
          ].slice(-60),
          patience: [...state.neurobus.patience, getNextVal(state.neurobus.patience, 0.04)].slice(
            -60
          ),
          threat: [...state.neurobus.threat, getNextVal(state.neurobus.threat, 0.01)].slice(-60),
          trust: [...state.neurobus.trust, getNextVal(state.neurobus.trust, 0.03)].slice(-60)
        };

        return {
          ...state,
          uptime_seconds: nextUptime,
          tick_rate: nextTickRate,
          pam: nextPam,
          neurobus: nextNeurobus
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
