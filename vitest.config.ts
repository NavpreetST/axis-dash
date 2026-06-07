import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  resolve: {
    alias: {
      $lib: resolve('./src/lib'),
      // SvelteKit's `$env/static/public` is a virtual module resolved by
      // the SvelteKit Vite plugin. Vitest does not load that plugin, so
      // any file importing the virtual (e.g. `src/lib/config.ts`) would
      // fail to load in the test runner. The stub keeps the import path
      // intact so production code needs no test-only branches.
      '$env/static/public': resolve('./src/lib/test/env-static-public-stub.ts')
    }
  },
  test: {
    environment: 'node',
    globals: true
  }
});
