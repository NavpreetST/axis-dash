/**
 * Resolved configuration for the live Helios bridge.
 *
 * Reads Vite public env vars at build/dev time. Defaults are tuned for
 * local Helios development (`http://localhost:8080` / `ws://localhost:8080`)
 * and live mode is OFF by default — the dashboard runs on the seeded
 * mock data until `PUBLIC_USE_LIVE_BRIDGE=true` is explicitly set.
 */
export const config = {
  /** Base URL for HTTP and SSE endpoints exposed by the Helios bridge. */
  heliosApiUrl: import.meta.env.PUBLIC_HELIOS_API_URL ?? 'http://localhost:8080',
  /** Base URL for WebSocket endpoints exposed by the Helios bridge. */
  heliosWsUrl: import.meta.env.PUBLIC_HELIOS_WS_URL ?? 'ws://localhost:8080',
  /**
   * Master switch for the live bridge. True only when the env var is
   * explicitly set to the string `"true"`; any other value (including
   * unset) keeps the dashboard on mock data.
   */
  useLiveBridge: import.meta.env.PUBLIC_USE_LIVE_BRIDGE === 'true'
} as const;

/** Inferred type of the resolved {@link config} object. */
export type Config = typeof config;
