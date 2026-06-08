import { describe, it, expect } from 'vitest';
import {
  formatUptime,
  pamThreshold,
  rpdOverBudget,
  rpdPercent,
  formatTickRate,
  scaleSparkline,
  formatRuntimeValue
} from './formatters';

// ── formatUptime ────────────────────────────────────────────────
describe('formatUptime', () => {
  it('formats hours and minutes, omitting seconds', () => {
    // 14h 22m 22s = 51742s → "14h 22m"
    expect(formatUptime(51742)).toBe('14h 22m');
  });

  it('formats zero seconds as 0h 0m', () => {
    expect(formatUptime(0)).toBe('0h 0m');
  });

  it('formats exact hours with 0 minutes', () => {
    expect(formatUptime(7200)).toBe('2h 0m');
  });

  it('formats sub-hour values', () => {
    expect(formatUptime(300)).toBe('0h 5m');
  });

  it('returns -- for negative values', () => {
    expect(formatUptime(-1)).toBe('--');
  });

  it('returns -- for NaN', () => {
    expect(formatUptime(NaN)).toBe('--');
  });

  it('returns -- for Infinity', () => {
    expect(formatUptime(Infinity)).toBe('--');
  });
});

// ── pamThreshold ────────────────────────────────────────────────
describe('pamThreshold', () => {
  it('returns green for pam >= 0.90', () => {
    expect(pamThreshold(0.91)).toBe('green');
    expect(pamThreshold(0.9)).toBe('green');
    expect(pamThreshold(1.0)).toBe('green');
  });

  it('returns amber for pam 0.83–0.89', () => {
    expect(pamThreshold(0.89)).toBe('amber');
    expect(pamThreshold(0.83)).toBe('amber');
    expect(pamThreshold(0.85)).toBe('amber');
  });

  it('returns red for pam < 0.83', () => {
    expect(pamThreshold(0.82)).toBe('red');
    expect(pamThreshold(0.5)).toBe('red');
    expect(pamThreshold(0)).toBe('red');
  });
});

// ── rpdOverBudget ───────────────────────────────────────────────
describe('rpdOverBudget', () => {
  it('returns false when under budget', () => {
    expect(rpdOverBudget(37, 240)).toBe(false);
  });

  it('returns false when exactly at budget', () => {
    expect(rpdOverBudget(240, 240)).toBe(false);
  });

  it('returns true when over budget', () => {
    expect(rpdOverBudget(241, 240)).toBe(true);
  });

  it('returns false when budget is zero (division guard)', () => {
    expect(rpdOverBudget(10, 0)).toBe(false);
  });

  it('returns false when budget is negative', () => {
    expect(rpdOverBudget(10, -5)).toBe(false);
  });
});

// ── rpdPercent ──────────────────────────────────────────────────
describe('rpdPercent', () => {
  it('computes correct percentage', () => {
    expect(rpdPercent(37, 240)).toBeCloseTo(15.42, 1);
  });

  it('clamps to 100 when over budget', () => {
    expect(rpdPercent(300, 240)).toBe(100);
  });

  it('returns 0 when budget is zero', () => {
    expect(rpdPercent(37, 0)).toBe(0);
  });

  it('returns 0 when budget is negative', () => {
    expect(rpdPercent(37, -10)).toBe(0);
  });

  it('returns 0 when used is 0', () => {
    expect(rpdPercent(0, 240)).toBe(0);
  });

  it('returns 100 when exactly at budget', () => {
    expect(rpdPercent(240, 240)).toBe(100);
  });

  it('clamps to 0 when used is negative', () => {
    expect(rpdPercent(-10, 240)).toBe(0);
  });
});

// ── formatTickRate ──────────────────────────────────────────────
describe('formatTickRate', () => {
  it('formats positive finite number to exactly 1 decimal digit', () => {
    expect(formatTickRate(9.845)).toBe('9.8');
    expect(formatTickRate(10)).toBe('10.0');
    expect(formatTickRate(0)).toBe('0.0');
  });

  it('returns -- for NaN', () => {
    expect(formatTickRate(NaN)).toBe('--');
  });

  it('returns -- for Infinity', () => {
    expect(formatTickRate(Infinity)).toBe('--');
  });
});

// ── scaleSparkline ──────────────────────────────────────────────
describe('scaleSparkline', () => {
  it('returns empty array for empty input', () => {
    expect(scaleSparkline([], 100, 50)).toEqual([]);
  });

  it('returns centered point for single-value array', () => {
    expect(scaleSparkline([0.5], 100, 50)).toEqual([{ x: 50, y: 25 }]);
  });

  it('centers flat datasets vertically', () => {
    expect(scaleSparkline([0.5, 0.5, 0.5], 100, 50)).toEqual([
      { x: 0, y: 25 },
      { x: 50, y: 25 },
      { x: 100, y: 25 }
    ]);
  });

  it('scales normal values to use full height and width', () => {
    const points = scaleSparkline([0.2, 0.8, 0.5], 100, 50);
    expect(points).toEqual([
      { x: 0, y: 50 },
      { x: 50, y: 0 },
      { x: 100, y: 25 }
    ]);
  });
});

// ── formatRuntimeValue ───────────────────────────────────────────
describe('formatRuntimeValue', () => {
  it('returns -- for null', () => {
    expect(formatRuntimeValue(null)).toBe('--');
  });

  it('returns -- for undefined', () => {
    expect(formatRuntimeValue(undefined)).toBe('--');
  });

  it('returns -- for empty string', () => {
    expect(formatRuntimeValue('')).toBe('--');
  });

  it('returns the string itself for a string value', () => {
    expect(formatRuntimeValue('lmdb')).toBe('lmdb');
  });

  it('returns the stringified number for a number value', () => {
    expect(formatRuntimeValue(4)).toBe('4');
  });

  it('returns the stringified number for a numeric string', () => {
    expect(formatRuntimeValue('12h')).toBe('12h');
  });

  it('joins an array with comma+space', () => {
    expect(formatRuntimeValue(['a', 'b'])).toBe('a, b');
  });

  it('compact-stringifies a plain object', () => {
    expect(formatRuntimeValue({ type: 'lmdb', path: '/data' })).toBe(
      '{"type":"lmdb","path":"/data"}'
    );
  });

  it('returns true/false for boolean values', () => {
    expect(formatRuntimeValue(true)).toBe('true');
    expect(formatRuntimeValue(false)).toBe('false');
  });

  it('handles 0 as a real value (not falsy)', () => {
    expect(formatRuntimeValue(0)).toBe('0');
  });
});
