#!/usr/bin/env bash
# scripts/drift-arch-guard.sh
#
# axis-dash drift / architecture guard -- Phase 4 step 1 STUB.
#
# Purpose (when fully implemented):
#   * Assert the UI's consumed event shape matches the frozen 8-field
#     event schema (schema_version = 1) emitted by Helios.
#   * Refuse imports from $lib/components into route handlers' server
#     code paths that would leak state-writer concerns into the dashboard.
#   * Diff the bridge client typings (src/lib/api/) against the contract
#     exposed by helios aegis/web/ and fail on drift.
#
# Today: exits 0 so the gate is wired and required, but does not yet
# enforce anything. Replacing the body of this script is the only thing
# needed to turn the gate on -- the CI job, branch protection, and PR
# template all already point at it.

set -euo pipefail

echo "[drift-arch-guard] STUB -- no checks enforced yet."
echo "[drift-arch-guard] Tracked TODOs:"
echo "  - event schema parity with helios (8 fields, schema_version=1)"
echo "  - bridge client typings vs aegis/web/ contract"
echo "  - layering rules: components -> stores -> api (no skipping)"
echo "[drift-arch-guard] OK (stub)."
