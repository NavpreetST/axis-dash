import { describe, it, expect } from 'vitest';
import { execSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { validateContract } from '../../../scripts/ci_state_guard.mjs';

const VALID_SOURCE = `
export interface TelemetryData {
  uptime_seconds: number;
  tick_rate: number;
  pam: number | null;
  rpd_used: number;
  rpd_budget: number;
  provider: string;
  connected: boolean;
  is_speaking: boolean;
  neurobus: Neurobus;
  neurobusHistory: NeurobusHistory;
  hidden_state: number[];
  runtime?: RuntimeInfo;
}

const applyLiveFrame = (frame: Partial<TelemetryData>) => {
  update((state) => {
    return {
      uptime_seconds: frame.uptime_seconds ?? state.uptime_seconds,
      tick_rate: frame.tick_rate ?? state.tick_rate,
      pam: frame.pam !== undefined ? frame.pam : state.pam,
      rpd_used: frame.rpd_used ?? state.rpd_used,
      rpd_budget: frame.rpd_budget ?? state.rpd_budget,
      provider: frame.provider ?? state.provider,
      is_speaking: frame.is_speaking ?? state.is_speaking,
      neurobus: frame.neurobus ?? state.neurobus,
      neurobusHistory: frame.neurobusHistory ?? state.neurobusHistory,
      hidden_state: frame.hidden_state ?? frame.h ?? state.hidden_state,
      runtime: frame.runtime ? { ...state.runtime, ...frame.runtime } : state.runtime
    };
  });
};
`;

describe('ci_state_guard contract validator', () => {
  it('passes on valid source', () => {
    const { errors } = validateContract(VALID_SOURCE);
    expect(errors).toHaveLength(0);
  });

  it('fails (throws) when TelemetryData interface cannot be parsed', () => {
    const badSource = `
export interface OtherData {
  uptime_seconds: number;
}
`;
    expect(() => validateContract(badSource)).toThrow('could not extract TelemetryData interface');
  });

  it('fails (throws) when applyLiveFrame cannot be parsed (fail closed on extraction miss)', () => {
    const badSource = `
export interface TelemetryData {
  uptime_seconds: number;
  tick_rate: number;
  pam: number | null;
  rpd_used: number;
  rpd_budget: number;
  provider: string;
  connected: boolean;
  is_speaking: boolean;
  neurobus: Neurobus;
  neurobusHistory: NeurobusHistory;
  hidden_state: number[];
  runtime?: RuntimeInfo;
}

const applyLiveFrameMismatchedName = () => {};
`;
    expect(() => validateContract(badSource)).toThrow(
      'drift guard could not locate the live-frame fields'
    );
  });

  it('fails when a field is missing from TelemetryData interface', () => {
    // Missing 'runtime' from the interface
    const source = VALID_SOURCE.replace('  runtime?: RuntimeInfo;', '');
    const { errors } = validateContract(source);
    expect(errors).toContain('TelemetryData missing field "runtime" (was present before)');
  });

  it('fails when applyLiveFrame no longer reads a required field', () => {
    // Missing 'frame.runtime' read
    const source = VALID_SOURCE.replace(
      'runtime: frame.runtime ? { ...state.runtime, ...frame.runtime } : state.runtime',
      'runtime: state.runtime'
    );
    const { errors } = validateContract(source);
    expect(errors).toContain('applyLiveFrame no longer reads "runtime" (was consumed before)');
  });

  it('exits with non-zero code (1) when runtime is missing from telemetry.ts', () => {
    const telemetryPath = resolve(__dirname, './telemetry.ts');
    const originalContent = readFileSync(telemetryPath, 'utf-8');

    // Remove runtime from the interface in the actual file temporarily
    const modifiedContent = originalContent.replace(/runtime\?: RuntimeInfo;/g, '');
    writeFileSync(telemetryPath, modifiedContent, 'utf-8');

    try {
      expect(() => {
        execSync('node scripts/ci_state_guard.mjs', { stdio: 'pipe' });
      }).toThrow();
    } finally {
      // Restore original file
      writeFileSync(telemetryPath, originalContent, 'utf-8');
    }
  });
});
