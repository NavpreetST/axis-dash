/**
 * Formatting utilities for KPI card display values.
 * Pure functions — no store dependencies — fully unit-testable.
 */

/**
 * Format an uptime duration in seconds to "Xh Ym" display string.
 * Omits seconds per spec (Q1).
 */
export function formatUptime(seconds: number): string {
  if (seconds < 0 || !Number.isFinite(seconds)) return '--';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

/**
 * Classify a PAM coherence value into a threshold bucket.
 * Green ≥ 0.90 | Amber 0.83–0.89 | Red < 0.83
 */
export function pamThreshold(pam: number): 'green' | 'amber' | 'red' {
  if (pam >= 0.9) return 'green';
  if (pam >= 0.83) return 'amber';
  return 'red';
}

/**
 * Check whether RPD usage exceeds the budget.
 */
export function rpdOverBudget(used: number, budget: number): boolean {
  return budget > 0 && used > budget;
}

/**
 * Compute RPD usage as a percentage, clamped to 0–100.
 * Returns 0 if budget is zero or negative (division guard).
 */
export function rpdPercent(used: number, budget: number): number {
  if (budget <= 0) return 0;
  return Math.max(0, Math.min(100, (used / budget) * 100));
}

/**
 * Format a tick rate value to exactly 1 decimal place.
 * Prevents layout shift from variable-width numbers (e.g. 9.8 vs 10.0123).
 */
export function formatTickRate(rate: number): string {
  if (!Number.isFinite(rate)) return '--';
  return rate.toFixed(1);
}

export interface SparklinePoint {
  x: number;
  y: number;
}

/**
 * Format a runtime sub-field value for display.
 * Objects are compact-stringified; arrays are joined; null/missing → `--`.
 */
export function formatRuntimeValue(v: unknown): string {
  if (v == null || v === '') return '--';
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (Array.isArray(v)) return v.join(', ');
  return JSON.stringify(v);
}

export function scaleSparkline(data: number[], width: number, height: number): SparklinePoint[] {
  if (!data || data.length === 0) return [];
  const n = data.length;

  if (n === 1) {
    return [{ x: width / 2, y: height / 2 }];
  }

  let min = data[0];
  let max = data[0];
  for (let i = 1; i < n; i++) {
    const v = data[i];
    if (v < min) min = v;
    if (v > max) max = v;
  }

  const range = max - min;
  const points: SparklinePoint[] = [];

  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * width;
    const y = range === 0 ? height / 2 : height - ((data[i] - min) / range) * height;
    points.push({ x: +x.toFixed(2), y: +y.toFixed(2) });
  }

  return points;
}
