/**
 * Vitest stub for SvelteKit's `$env/static/public` virtual module.
 *
 * SvelteKit virtuals are only resolved by the SvelteKit Vite plugin.
 * Vitest does not load that plugin, so any `.ts` file that imports
 * `$env/static/public` (including `src/lib/config.ts`) blows up with
 * `ERR_MODULE_NOT_FOUND` when loaded by the test runner. This shim
 * keeps the import path the same so production code does not need a
 * test-only branch, while letting the test environment control the
 * values via `process.env`.
 *
 * Defaults are intentionally safe: `PUBLIC_USE_LIVE_BRIDGE` is
 * `'false'`, which keeps the dashboard on the seeded mock data and
 * prevents the test runner from opening real WebSocket / SSE
 * connections. CI can override any of these by exporting the
 * corresponding `process.env` variable before invoking vitest.
 */
const read = (key: string): string | undefined => {
  const v = process.env[key];
  return typeof v === 'string' && v.length > 0 ? v : undefined;
};

export const PUBLIC_HELIOS_API_URL: string = read('PUBLIC_HELIOS_API_URL') ?? '';
export const PUBLIC_HELIOS_WS_URL: string = read('PUBLIC_HELIOS_WS_URL') ?? '';
export const PUBLIC_USE_LIVE_BRIDGE: string = read('PUBLIC_USE_LIVE_BRIDGE') ?? 'false';
export const PUBLIC_SUPABASE_URL: string = read('PUBLIC_SUPABASE_URL') ?? '';
export const PUBLIC_SUPABASE_ANON_KEY: string = read('PUBLIC_SUPABASE_ANON_KEY') ?? '';
