/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL for HTTP/SSE endpoints exposed by the Helios bridge. */
  readonly PUBLIC_HELIOS_API_URL?: string;
  /** Base URL for WebSocket endpoints exposed by the Helios bridge. */
  readonly PUBLIC_HELIOS_WS_URL?: string;
  /**
   * Master switch for the live bridge. When `"true"`, the dashboard
   * consumes the real Helios bridge; when unset or any other value,
   * mock telemetry / logs / chat run locally. Default: off.
   */
  readonly PUBLIC_USE_LIVE_BRIDGE?: string;
  /**
   * Auth transport strategy for WS / SSE. Browser WebSocket and
   * `EventSource` cannot set the `Authorization` header, so the token
   * has to travel in the URL itself unless another channel is used.
   * - `"query"` (default): appends `?token=...` to the URL
   * - `"protocol"`: reserved for `Sec-WebSocket-Protocol` (not yet wired)
   * - `"cookie"`: reserved for cookie-based auth (not yet wired)
   * - `"none"`: no auth transport (local dev only)
   */
  readonly PUBLIC_HELIOS_AUTH_TRANSPORT?: 'query' | 'protocol' | 'cookie' | 'none' | string;
  /**
   * Build-time bearer token fallback. When set, used by the API client
   * if no token is present in localStorage. Useful for non-interactive
   * deployments (e.g. demos / smoke tests). Inlined into the bundle
   * at build time — do not put a high-value token here in production.
   */
  readonly PUBLIC_HELIOS_TOKEN?: string;
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare global {
  namespace App {
    // interface Error {}
    // interface Locals {}
    // interface PageData {}
    // interface PageState {}
    // interface Platform {}
  }
}

export {};
