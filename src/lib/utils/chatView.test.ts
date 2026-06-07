import { describe, it, expect } from 'vitest';
import { coalesceConsecutive, isPinnedToBottom, PIN_THRESHOLD_PX } from './chatView.js';
import type { ChatMessage } from '$lib/stores/chat';

const mk = (
  id: string,
  sender: ChatMessage['sender'],
  text: string,
  ts = '18:04'
): ChatMessage => ({
  id,
  sender,
  text,
  timestamp: ts
});

describe('coalesceConsecutive', () => {
  it('returns an empty array for empty input', () => {
    expect(coalesceConsecutive([])).toEqual([]);
  });

  it('keeps a single message as a single group with count 1', () => {
    const out = coalesceConsecutive([mk('a', 'aegis', 'hello')]);
    expect(out).toHaveLength(1);
    expect(out[0].count).toBe(1);
    expect(out[0].text).toBe('hello');
  });

  it('keeps distinct messages as separate rows even when adjacent', () => {
    const out = coalesceConsecutive([
      mk('a', 'aegis', 'first'),
      mk('b', 'aegis', 'second'),
      mk('c', 'aegis', 'third')
    ]);
    expect(out.map((g) => g.text)).toEqual(['first', 'second', 'third']);
    expect(out.map((g) => g.count)).toEqual([1, 1, 1]);
  });

  it('coalesces identical consecutive messages and increments the counter', () => {
    // The exact case from the bug report: bridge repeating
    // `{"error":"socket_unavailable",...}` while the daemon is down.
    const errText = '{"error":"socket_unavailable","sock":"/run/aegis/aegis.sock"}';
    const out = coalesceConsecutive([
      mk('1', 'aegis', errText),
      mk('2', 'aegis', errText),
      mk('3', 'aegis', errText),
      mk('4', 'aegis', errText),
      mk('5', 'aegis', errText)
    ]);
    expect(out).toHaveLength(1);
    expect(out[0].count).toBe(5);
    expect(out[0].text).toBe(errText);
    expect(out[0].key).toBe('1');
  });

  it('does NOT coalesce identical text from different senders', () => {
    const out = coalesceConsecutive([
      mk('1', 'aegis', 'ok'),
      mk('2', 'you', 'ok'),
      mk('3', 'aegis', 'ok')
    ]);
    expect(out).toHaveLength(3);
    expect(out.map((g) => g.sender)).toEqual(['aegis', 'you', 'aegis']);
  });

  it('restarts the counter when a distinct message breaks the run', () => {
    const out = coalesceConsecutive([
      mk('1', 'aegis', 'err'),
      mk('2', 'aegis', 'err'),
      mk('3', 'aegis', 'ok'),
      mk('4', 'aegis', 'err'),
      mk('5', 'aegis', 'err')
    ]);
    expect(out).toHaveLength(3);
    expect(out.map((g) => [g.text, g.count])).toEqual([
      ['err', 2],
      ['ok', 1],
      ['err', 2]
    ]);
  });

  it('preserves the FIRST occurrence id and timestamp for each group', () => {
    const out = coalesceConsecutive([
      mk('first', 'aegis', 'x', '18:00'),
      mk('second', 'aegis', 'x', '18:01'),
      mk('third', 'aegis', 'x', '18:02')
    ]);
    expect(out[0].key).toBe('first');
    expect(out[0].timestamp).toBe('18:00');
    expect(out[0].count).toBe(3);
  });

  it('treats messages with the same text but different affect as distinct', () => {
    const a: ChatMessage = {
      id: '1',
      sender: 'aegis',
      text: 'hi',
      timestamp: '18:00',
      affect: 'calm'
    };
    const b: ChatMessage = {
      id: '2',
      sender: 'aegis',
      text: 'hi',
      timestamp: '18:01',
      affect: 'alert'
    };
    const c: ChatMessage = {
      id: '3',
      sender: 'aegis',
      text: 'hi',
      timestamp: '18:02',
      affect: 'calm'
    };
    const out = coalesceConsecutive([a, b, c]);
    expect(out).toHaveLength(3);
    expect(out.map((g) => g.affect)).toEqual(['calm', 'alert', 'calm']);
  });

  it('handles a long mixed run without dropping entries from the count', () => {
    // Stress: alternating identical pairs and distinct singletons.
    const msgs: ChatMessage[] = [];
    for (let i = 0; i < 100; i++) {
      msgs.push(mk(`a-${i}`, 'aegis', i % 2 === 0 ? 'even' : 'odd'));
    }
    const out = coalesceConsecutive(msgs);
    // 50 even, 50 odd alternating → 100 groups, each count 1
    expect(out).toHaveLength(100);
    expect(out.every((g) => g.count === 1)).toBe(true);
  });

  it('input N → output ≤ N (coalesce never grows the list)', () => {
    const msgs: ChatMessage[] = [];
    for (let i = 0; i < 50; i++) {
      msgs.push(mk(`id-${i}`, 'aegis', 'same text'));
    }
    const out = coalesceConsecutive(msgs);
    expect(out).toHaveLength(1);
    expect(out[0].count).toBe(50);
  });
});

describe('isPinnedToBottom', () => {
  it('returns true when scrollTop is exactly at the bottom', () => {
    // scrollHeight = 1000, clientHeight = 200, scrollTop = 800 → 800 + 200 = 1000 = scrollHeight
    expect(isPinnedToBottom(800, 200, 1000)).toBe(true);
  });

  it('returns true when scrollTop is within the threshold of the bottom', () => {
    // 780 + 200 = 980, scrollHeight = 1000, gap = 20, threshold = 40 → pinned
    expect(isPinnedToBottom(780, 200, 1000)).toBe(true);
  });

  it('returns true at the exact threshold boundary', () => {
    // 760 + 200 = 960, scrollHeight = 1000, gap = 40, threshold = 40 → pinned (>=)
    expect(isPinnedToBottom(760, 200, 1000)).toBe(true);
  });

  it('returns false when scrollTop is more than the threshold above the bottom', () => {
    // 750 + 200 = 950, scrollHeight = 1000, gap = 50, threshold = 40 → not pinned
    expect(isPinnedToBottom(750, 200, 1000)).toBe(false);
  });

  it('returns false when the user has scrolled all the way to the top', () => {
    expect(isPinnedToBottom(0, 200, 1000)).toBe(false);
  });

  it('returns true when content fits entirely in the viewport (no overflow)', () => {
    // scrollHeight == clientHeight, scrollTop = 0 → always pinned
    expect(isPinnedToBottom(0, 500, 500)).toBe(true);
  });

  it('respects a custom threshold', () => {
    // Gap is 50, threshold lowered to 100 → pinned
    expect(isPinnedToBottom(750, 200, 1000, 100)).toBe(true);
    // Gap is 50, threshold raised to 10 → not pinned
    expect(isPinnedToBottom(750, 200, 1000, 10)).toBe(false);
  });

  it('PIN_THRESHOLD_PX is the documented 40px default', () => {
    expect(PIN_THRESHOLD_PX).toBe(40);
  });

  it('behaves correctly for the daemon-flood scenario', () => {
    // Simulate: chat is at the bottom, then the bridge fires 10
    // identical error messages in quick succession. The user is
    // pinned (read latest live), so isPinnedToBottom stays true on
    // each new scroll position. The auto-scroll effect will then
    // drag them down to the latest message every time.
    let scrollTop = 800;
    const clientHeight = 200;
    let scrollHeight = 1000;
    for (let i = 0; i < 10; i++) {
      expect(isPinnedToBottom(scrollTop, clientHeight, scrollHeight)).toBe(true);
      // Simulate a new message growing the content and the user
      // being auto-scrolled to keep up:
      scrollHeight += 40;
      scrollTop += 40;
    }
  });
});
