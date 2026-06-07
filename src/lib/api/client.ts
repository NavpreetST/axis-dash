import { config } from '$lib/config';

/**
 * localStorage key used by the login page to persist the session bearer token.
 */
const TOKEN_KEY = 'HELIOS_TOKEN';

/**
 * Read the build-time fallback token. Vite inlines `PUBLIC_*` env vars
 * at build time, so this is available in the deployed bundle but only
 * reflects whatever was set when the bundle was produced. A Vercel
 * env-var change requires a redeploy for it to take effect.
 */
function readBuildToken(): string | null {
  const v = import.meta.env.PUBLIC_HELIOS_TOKEN;
  return typeof v === 'string' && v.length > 0 ? v : null;
}

/**
 * Read the current bearer token. Resolution order:
 * 1. `localStorage.HELIOS_TOKEN` (set by the login page)
 * 2. Build-time `PUBLIC_HELIOS_TOKEN` env var (Vercel deployment setting)
 *
 * Returns null during SSR or when no token is available.
 */
export function getToken(): string | null {
  if (typeof localStorage !== 'undefined') {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (stored) return stored;
  }
  return readBuildToken();
}

/**
 * Fetch wrapper that injects an `Authorization: Bearer <token>` header
 * from localStorage when a token is present. Used for HTTP endpoints
 * (e.g. `/health`).
 */
export function fetchWithAuth(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(input, { ...init, headers });
}

/**
 * Build a full WebSocket URL by appending `path` to the configured WS base.
 * Token transport is applied separately via {@link applyAuthToUrl}.
 */
export function buildWsUrl(path: string): string {
  const base = config.heliosWsUrl.replace(/\/$/, '');
  return `${base}${path}`;
}

/**
 * Build a full HTTP URL by appending `path` to the configured API base.
 * Used for both regular HTTP fetches and SSE (`EventSource` cannot
 * send custom headers, so SSE URLs also go through the HTTP base).
 */
export function buildHttpUrl(path: string): string {
  const base = config.heliosApiUrl.replace(/\/$/, '');
  return `${base}${path}`;
}

/**
 * Build a full SSE URL. Kept as a separate name from {@link buildHttpUrl}
 * to allow future divergence (e.g. dedicated SSE host). Today it delegates
 * to the HTTP builder.
 */
export function buildSseUrl(path: string): string {
  return buildHttpUrl(path);
}

/**
 * Strategy for embedding the bearer token into WS / SSE URLs.
 *
 * Browser `WebSocket` and `EventSource` cannot set the `Authorization`
 * header, so the token must travel in the URL itself unless the bridge
 * accepts it via a different channel (cookie, subprotocol, etc.).
 *
 * - `query` (default): appends `?token=...` to the URL. Works in all
 *   browsers and is the only universally supported option.
 * - `protocol`: reserved for `Sec-WebSocket-Protocol: bearer.<token>`.
 *   NOT YET WIRED — the WS clients still pass the bare URL to
 *   `new WebSocket(url)` so the token would be dropped. Implement
 *   before enabling in production.
 * - `cookie`: reserved for cookie-based auth. NOT YET WIRED — the
 *   clients do not read or set cookies. Implement before enabling.
 * - `none`: no auth transport; the bridge must accept unauthenticated
 *   connections. Intended for local dev only.
 *
 * If a non-`query` transport is selected while a token is present, the
 * transport will silently return the URL unchanged and the bridge will
 * reject the connection. See `getAuthTransport()` for the runtime
 * warning emitted in that case.
 */
export interface BridgeAuthTransport {
  type: 'query' | 'protocol' | 'cookie' | 'none';
  apply(url: string, token: string): string;
}

export const authTransports: Record<string, BridgeAuthTransport> = {
  query: {
    type: 'query',
    apply(url: string, token: string): string {
      const u = new URL(url);
      u.searchParams.set('token', token);
      return u.toString();
    }
  },
  protocol: {
    type: 'protocol',
    apply(url: string, _token: string): string {
      void _token;
      return url;
    }
  },
  cookie: {
    type: 'cookie',
    apply(url: string, _token: string): string {
      void _token;
      return url;
    }
  },
  none: {
    type: 'none',
    apply(url: string, _token: string): string {
      void _token;
      return url;
    }
  }
};

/**
 * Resolve the active auth transport from the
 * `PUBLIC_HELIOS_AUTH_TRANSPORT` env var. Defaults to `query`.
 * Emits a `console.warn` when a transport that does not yet wire the
 * token (protocol / cookie / none) is selected while a token is present,
 * so the misconfiguration is visible during development.
 */
export function getAuthTransport(): BridgeAuthTransport {
  const mode = import.meta.env.PUBLIC_HELIOS_AUTH_TRANSPORT ?? 'query';
  const transport = authTransports[mode] ?? authTransports.query;
  if (typeof console !== 'undefined' && mode !== 'query' && mode !== 'none') {
    const token = getToken();
    if (token) {
      console.warn(
        `[helios] PUBLIC_HELIOS_AUTH_TRANSPORT="${mode}" is selected but not yet wired ` +
          'into the WS/SSE clients — the token will be dropped. Use "query" until ' +
          'the transport is implemented.'
      );
    }
  }
  return transport;
}

/**
 * Apply the configured auth transport to a URL. When no token is stored
 * the URL is returned unchanged.
 */
export function applyAuthToUrl(url: string): string {
  const token = getToken();
  if (!token) return url;
  const transport = getAuthTransport();
  return transport.apply(url, token);
}

/**
 * One-shot `GET /health` probe. Returns `true` on any 2xx response,
 * `false` on network failure or non-2xx. Safe to call repeatedly.
 */
export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetchWithAuth(buildHttpUrl('/health'), { method: 'GET' });
    return res.ok;
  } catch {
    return false;
  }
}
