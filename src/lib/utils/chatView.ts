import type { ChatMessage } from '$lib/stores/chat';

/**
 * A group of consecutive messages in the chat log that share the same
 * `(sender, text, affect)` triple. The view layer renders one row per
 * group and shows a `×N` repeat counter when `count > 1`.
 *
 * The underlying store still holds every individual message — the
 * coalesce is display-only, so a downstream consumer (debug export,
 * copy-paste, etc.) can recover the full event stream.
 */
export interface CoalescedMessage {
  /** Stable key for Svelte's `{#each ... (key)}` keyed rendering. */
  key: string;
  sender: ChatMessage['sender'];
  text: string;
  /** Timestamp of the FIRST occurrence in the group. */
  timestamp: string;
  affect: ChatMessage['affect'];
  /** 1 for a single message, N for N consecutive duplicates. */
  count: number;
}

/**
 * Coalesce consecutive messages with identical `(sender, text, affect)`
 * into a single row. The first message's id and timestamp are kept as
 * the row's identity. Distinct messages — even adjacent ones with
 * matching text but different senders — always get their own row.
 *
 * Stable: a non-empty input always produces a non-empty output. Order
 * is preserved.
 */
export function coalesceConsecutive(messages: ChatMessage[]): CoalescedMessage[] {
  const out: CoalescedMessage[] = [];
  for (const msg of messages) {
    const last = out[out.length - 1];
    if (
      last &&
      last.sender === msg.sender &&
      last.text === msg.text &&
      last.affect === msg.affect
    ) {
      last.count += 1;
    } else {
      out.push({
        key: msg.id,
        sender: msg.sender,
        text: msg.text,
        timestamp: msg.timestamp,
        affect: msg.affect,
        count: 1
      });
    }
  }
  return out;
}

/** Maximum gap (in pixels) between the bottom of the scroll viewport
 * and the bottom of the scrollable content for the user to be
 * considered "pinned to the bottom". Tuned for chat panels: small
 * enough that being 1-2 messages up still counts as pinned, large
 * enough that sub-pixel rounding and momentum scrolling don't flip
 * the flag. */
export const PIN_THRESHOLD_PX = 40;

/**
 * True when the scroll viewport is at (or within {@link PIN_THRESHOLD_PX}
 * of) the bottom of the scrollable content. Used to decide whether a
 * new message should auto-scroll the user to the latest entry, or
 * leave them where they are.
 */
export function isPinnedToBottom(
  scrollTop: number,
  clientHeight: number,
  scrollHeight: number,
  threshold: number = PIN_THRESHOLD_PX
): boolean {
  return scrollTop + clientHeight >= scrollHeight - threshold;
}
