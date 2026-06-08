import type { LogLine } from '$lib/stores/logs';

export interface ActivityItem {
  key: string;
  time: string;
  source: string;
  type: LogLine['type'];
  message: string;
  offsetSec: number;
}

const ONE_MIN = 60;
const FIVE_MIN = 300;

/**
 * Convert raw log lines to a timeline of activity items.
 * Malformed entries are preserved — missing or non-string fields
 * are replaced with safe defaults.
 */
export function toActivityItems(logs: LogLine[]): ActivityItem[] {
  const now = Date.now();
  const out: ActivityItem[] = [];

  for (const log of logs) {
    const ts = typeof log.timestamp === 'string' ? log.timestamp : '';
    const source = typeof log.source === 'string' ? log.source : 'sys';
    const type: LogLine['type'] = ['info', 'success', 'warning', 'error'].includes(log.type)
      ? log.type
      : 'info';
    const message = typeof log.message === 'string' ? log.message : '';

    const id =
      typeof log.id === 'string' && log.id
        ? log.id
        : `act-${stableHash(ts + source + type + message)}`;

    const parsed = parseTimestamp(ts);
    const offsetSec = parsed != null ? Math.floor((now - parsed) / 1000) : 0;

    out.push({
      key: id,
      time: offsetSec <= 0 ? 'just now' : formatOffset(offsetSec),
      source,
      type,
      message,
      offsetSec
    });
  }

  return out;
}

/** Deterministic hash from a string — stable across renders. */
function stableHash(s: string): string {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    const chr = s.charCodeAt(i);
    hash = (hash << 5) - hash + chr;
    hash |= 0;
  }
  return Math.abs(hash).toString(36);
}

function parseTimestamp(ts: string): number | null {
  if (!ts) return null;
  const today = new Date();
  const parts = ts.split(':');
  if (parts.length === 3) {
    const h = parseInt(parts[0], 10);
    const m = parseInt(parts[1], 10);
    const s = parseInt(parts[2], 10);
    if (
      !isNaN(h) &&
      !isNaN(m) &&
      !isNaN(s) &&
      h >= 0 &&
      h <= 23 &&
      m >= 0 &&
      m <= 59 &&
      s >= 0 &&
      s <= 59
    ) {
      today.setHours(h, m, s, 0);
      return today.getTime();
    }
  }
  const d = new Date(ts);
  return isNaN(d.getTime()) ? null : d.getTime();
}

function formatOffset(sec: number): string {
  if (sec < ONE_MIN) return `${sec}s ago`;
  if (sec < FIVE_MIN) return `${Math.floor(sec / ONE_MIN)}m ago`;
  return `${Math.floor(sec / ONE_MIN)}m ago`;
}
