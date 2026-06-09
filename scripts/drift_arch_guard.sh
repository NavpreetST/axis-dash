#!/usr/bin/env bash
# scripts/drift_arch_guard.sh
#
# Helios drift / architecture guard -- Phase 4 step 1 STUB.
#
# Purpose (when fully implemented):
#   * Assert the event schema is exactly 8 fields with schema_version = 1
#     (the frozen contract from AGENTS.md).
#   * Refuse cross-layer imports that would let aegis/web/ reach into
#     aegis/nexus/ internals (and vice versa) outside the documented
#     contracts in aegis/nexus/neurobus.py.
#   * Diff the committed JSONL record shape against producers in
#     aegis/observability/ and fail on drift.
#
# Today: exits 0 so the gate is wired and required, but does not yet
# enforce anything. Replacing the body of this script is the only thing
# needed to turn the gate on -- the CI job, branch protection, and PR
# template all already point at it.

set -euo pipefail

echo "[drift-arch-guard] STUB -- no checks enforced yet."
echo "[drift-arch-guard] Tracked TODOs:"
echo "  - event schema invariants (8 fields, schema_version=1)"
echo "  - layering rules between aegis/web, aegis/nexus, aegis/renderer"
echo "  - JSONL producer/consumer shape parity"
echo "[drift-arch-guard] OK (stub)."
