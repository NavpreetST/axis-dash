export const config = {
  heliosApiUrl: import.meta.env.PUBLIC_HELIOS_API_URL ?? 'http://localhost:8080',
  heliosWsUrl: import.meta.env.PUBLIC_HELIOS_WS_URL ?? 'ws://localhost:8080',
  useLiveBridge: import.meta.env.PUBLIC_USE_LIVE_BRIDGE === 'true'
} as const;

export type Config = typeof config;
