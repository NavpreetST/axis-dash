/**
 * Resolved configuration for the live Helios bridge.
 *
 * Reads Vite public env vars at build/dev time. Defaults use secure
 * `https` / `wss` schemes against `localhost` (treated as a secure
 * context by browsers, so local dev against a non-TLS bridge works),
 * and live mode is OFF by default — the dashboard runs on the seeded
 * mock data until `PUBLIC_USE_LIVE_BRIDGE` is set to a truthy value.
 *
 * NOTE: uses SvelteKit's `$env/static/public` rather than
 * `import.meta.env.PUBLIC_*`. The SvelteKit Vite plugin only inlines
 * `import.meta.env.PUBLIC_*` in Svelte components / route modules —
 * in plain `.ts` files it stays `undefined`, which is why the live
 * bridge never engaged even with the env vars set. `$env/static/public`
 * is reliably inlined everywhere at build time.
 *
 * Validation runs once at module load: insecure schemes are allowed for
 * loopback hosts and flagged in the console for everything else.
 */
import {
  PUBLIC_HELIOS_API_URL,
  PUBLIC_HELIOS_WS_URL,
  PUBLIC_USE_LIVE_BRIDGE
} from '$env/static/public';

/**
 * Hosts that browsers treat as secure contexts even over plain http/ws.
 * Used by {@link validateHeliosUrls} to permit insecure schemes only
 * for local development.
 */
const LOCALHOST_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

/**
 * True when a URL's scheme is one of the plaintext transports (`http` / `ws`).
 */
function isInsecureScheme(scheme: string): boolean {
  return scheme === 'http' || scheme === 'ws';
}

/**
 * Parse a string env var as a boolean, accepting the common truthy
 * variants dashboard UIs produce. Case-insensitive and whitespace-tolerant.
 *
 * Accepts: `"true"`, `"1"`, `"yes"`, `"on"`, `"enabled"`.
 * Anything else (including unset and empty string) is `false`.
 */
export function parseBool(raw: string | undefined | null): boolean {
  if (typeof raw !== 'string') return false;
  const v = raw.trim().toLowerCase();
  return v === 'true' || v === '1' || v === 'yes' || v === 'on' || v === 'enabled';
}

/**
 * Validate the resolved Helios bridge URLs.
 *
 * - Permits `http` / `ws` for `localhost`, `127.0.0.1`, and `::1` so local
 *   development against a non-TLS bridge keeps working.
 * - Warns in development and logs a `console.error` in production when a
 *   non-loopback host is reached over an insecure scheme, so the
 *   misconfiguration is visible in DevTools / browser console without
 *   crashing the app (a reverse proxy terminating TLS in front of the
 *   bridge is a legitimate production setup).
 *
 * Returns the parsed `URL` objects so callers can use the validated form
 * without re-parsing. Safe to call during SSR (no-ops when `console` is
 * unavailable).
 */
function validateHeliosUrls(api: string, ws: string): { api: URL; ws: URL } {
  const parsedApi = new URL(api);
  const parsedWs = new URL(ws);

  const isProd = import.meta.env.PROD === true;
  const log = isProd ? console.error : console.warn;
  const tag = '[helios]';

  for (const { label, parsed } of [
    { label: 'PUBLIC_HELIOS_API_URL', parsed: parsedApi },
    { label: 'PUBLIC_HELIOS_WS_URL', parsed: parsedWs }
  ]) {
    if (
      isInsecureScheme(parsed.protocol.replace(':', '')) &&
      !LOCALHOST_HOSTS.has(parsed.hostname)
    ) {
      log(
        `${tag} ${label}=${parsed.toString()} uses an insecure scheme ` +
          `(${parsed.protocol}) for a non-loopback host (${parsed.hostname}). ` +
          'Authentication tokens and telemetry will be transmitted in cleartext. ' +
          'Use https:// / wss://, or terminate TLS in a reverse proxy in front of the bridge.'
      );
    }
  }

  return { api: parsedApi, ws: parsedWs };
}

export const config = {
  /** Base URL for HTTP and SSE endpoints exposed by the Helios bridge. */
  heliosApiUrl: PUBLIC_HELIOS_API_URL ?? 'https://localhost:8080',
  /** Base URL for WebSocket endpoints exposed by the Helios bridge. */
  heliosWsUrl: PUBLIC_HELIOS_WS_URL ?? 'wss://localhost:8080',
  /**
   * Master switch for the live bridge. True when `PUBLIC_USE_LIVE_BRIDGE`
   * resolves to a truthy string (`true` / `1` / `yes` / `on` / `enabled`,
   * case-insensitive). Any other value (including unset) keeps the
   * dashboard on mock data.
   */
  useLiveBridge: parseBool(PUBLIC_USE_LIVE_BRIDGE)
} as const;

// Run validation once at module load. Failures to parse are surfaced by
// the `URL` constructor throwing — the dashboard will not boot with a
// malformed bridge URL, which is the correct behaviour.
validateHeliosUrls(config.heliosApiUrl, config.heliosWsUrl);

// One-line visibility into what the deployed bundle actually resolved to.
// `PUBLIC_*` env vars are inlined at build time — a redeploy is required
// for changes to land in the deployed bundle. If `useLiveBridge` is
// unexpectedly false in production, the raw env-var line below is the
// fastest way to see whether the variable is unset, mistyped, or just
// stale relative to the last build.
if (typeof console !== 'undefined') {
  const raw = PUBLIC_USE_LIVE_BRIDGE;
  console.info('[helios] config', {
    useLiveBridge: config.useLiveBridge,
    heliosApiUrl: config.heliosApiUrl,
    heliosWsUrl: config.heliosWsUrl,
    rawPublicUseLiveBridge: typeof raw === 'string' && raw.length > 0 ? raw : '(unset)'
  });
}

/** Inferred type of the resolved {@link config} object. */
export type Config = typeof config;
