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
