#!/usr/bin/env node
/**
 * CI drift / arch guard — validate the frontend ↔ /state contract.
 *
 * Parses src/lib/stores/telemetry.ts and enforces:
 *   1. The TelemetryData interface has NOT lost any fields it currently has
 *      (prevents accidental regressions).
 *   2. The applyLiveFrame function still reads all previously-consumed fields.
 *   3. Backend fields not yet consumed by the frontend are WARNINGS only.
 *
 * The backend's 14-field contract is guarded separately in the helios repo.
 * This guard protects the FRONTEND from accidentally dropping fields it
 * already consumes.
 *
 * Usage: node scripts/ci_state_guard.mjs
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const TELEMETRY_TS = resolve(
  import.meta.dirname || fileURLToPath(new URL('.', import.meta.url)),
  '../src/lib/stores/telemetry.ts'
);

// Fields currently in TelemetryData.  If any of these are removed in a PR,
// this guard FAILS.  New fields may be added freely.
export const EXPECTED_IFACE_FIELDS = [
  'uptime_seconds',
  'tick_rate',
  'pam',
  'rpd_used',
  'rpd_budget',
  'provider',
  'connected',
  'is_speaking',
  'neurobus',
  'neurobusHistory',
  'hidden_state',
  'runtime'
];

// Fields that applyLiveFrame() currently reads from the frame.  If any are
// removed, this guard FAILS.
export const EXPECTED_LIVE_FRAME_FIELDS = [
  'neurobus',
  'uptime_seconds',
  'tick_rate',
  'pam',
  'rpd_used',
  'rpd_budget',
  'provider',
  'is_speaking',
  'hidden_state',
  'runtime'
];

/**
 * @param {string} source
 * @returns {string[] | null}
 */
export function extractInterfaceFields(source) {
  const ifaceMatch = source.match(/interface\s+TelemetryData\s*\{([\s\S]*?)\n\s*\}/);
  if (!ifaceMatch) return null;

  const body = ifaceMatch[1];
  const fields = [];
  const fieldRegex = /^\s+(\w+)\s*[?:]/gm;
  let m;
  while ((m = fieldRegex.exec(body)) !== null) {
    fields.push(m[1]);
  }
  return fields;
}

/**
 * @param {string} source
 * @returns {string[] | null}
 */
export function extractApplyLiveFrameFields(source) {
  const fnMatch = source.match(
    /const\s+applyLiveFrame\s*=\s*\([^)]*\)\s*=>\s*\{([\s\S]*?)\n\s*\};/
  );
  if (!fnMatch) return null;

  const body = fnMatch[1];
  const fields = [];
  const frameFieldRegex = /frame\.(\w+)/g;
  let m;
  const seen = new Set();
  while ((m = frameFieldRegex.exec(body)) !== null) {
    if (!seen.has(m[1])) {
      seen.add(m[1]);
      fields.push(m[1]);
    }
  }
  return fields;
}

/**
 * @param {string} source
 * @returns {{ ifaceFields: string[], liveFrameFields: string[], errors: string[] }}
 */
export function validateContract(source) {
  const errors = [];
  const ifaceFields = extractInterfaceFields(source);
  if (!ifaceFields) {
    throw new Error('ERROR: could not extract TelemetryData interface');
  }

  const liveFrameFields = extractApplyLiveFrameFields(source);
  if (!liveFrameFields || liveFrameFields.length === 0) {
    throw new Error('ERROR: drift guard could not locate the live-frame fields — refusing to pass');
  }

  // Check TelemetryData hasn't lost any fields
  for (const field of EXPECTED_IFACE_FIELDS) {
    if (!ifaceFields.includes(field)) {
      errors.push(`TelemetryData missing field "${field}" (was present before)`);
    }
  }

  // Check applyLiveFrame hasn't lost any field reads
  for (const field of EXPECTED_LIVE_FRAME_FIELDS) {
    if (!liveFrameFields.includes(field)) {
      errors.push(`applyLiveFrame no longer reads "${field}" (was consumed before)`);
    }
  }

  return { ifaceFields, liveFrameFields, errors };
}

function main() {
  let source;
  try {
    source = readFileSync(TELEMETRY_TS, 'utf-8');
  } catch {
    console.error(`ERROR: cannot read ${TELEMETRY_TS}`);
    process.exit(1);
  }

  try {
    const { ifaceFields, liveFrameFields, errors } = validateContract(source);
    console.log(`TelemetryData fields: ${ifaceFields.join(', ')}`);
    console.log(`applyLiveFrame reads:  ${liveFrameFields.join(', ')}`);

    if (errors.length > 0) {
      console.error('\n*** DRIFT GUARD FAILED ***');
      for (const e of errors) {
        console.error(`  - ${e}`);
      }
      console.error(
        '\nTo fix: if the field removal is intentional, update\n' +
          'EXPECTED_IFACE_FIELDS / EXPECTED_LIVE_FRAME_FIELDS in this script\n' +
          "and get Navpreet's approval."
      );
      process.exit(1);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(message);
    process.exit(1);
  }

  console.log('\nOK — frontend ↔ /state contract is intact (no regressions).');
}

const isMain =
  process.argv[1] && resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1]);
if (isMain) {
  main();
}
