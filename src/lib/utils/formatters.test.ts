import { describe, it, expect } from 'vitest';
import {
  formatUptime,
  pamThreshold,
  rpdOverBudget,
  rpdPercent,
  formatTickRate
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
  it('formats to exactly 1 decimal place', () => {
    expect(formatTickRate(9.8)).toBe('9.8');
  });

  it('pads whole numbers with .0', () => {
    expect(formatTickRate(10)).toBe('10.0');
  });

  it('truncates extra decimals', () => {
    expect(formatTickRate(9.8123)).toBe('9.8');
  });

  it('formats zero', () => {
    expect(formatTickRate(0)).toBe('0.0');
  });

  it('returns -- for NaN', () => {
    expect(formatTickRate(NaN)).toBe('--');
  });

  it('returns -- for Infinity', () => {
    expect(formatTickRate(Infinity)).toBe('--');
  });
});
