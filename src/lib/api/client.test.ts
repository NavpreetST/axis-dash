import { describe, it, expect } from 'vitest';
import { redactAuthFromUrl } from './client.js';

describe('redactAuthFromUrl', () => {
  it('replaces ?token= with ***', () => {
    const redacted = redactAuthFromUrl('wss://bridge.example.com/state?token=secret123');
    expect(redacted).toBe('wss://bridge.example.com/state?token=***');
    expect(redacted).not.toContain('secret123');
  });

  it('preserves host, path, and non-sensitive query parameters', () => {
    const redacted = redactAuthFromUrl(
      'wss://bridge.example.com/state?v=2&token=secret123&debug=1'
    );
    expect(redacted).toContain('wss://bridge.example.com/state');
    expect(redacted).toContain('v=2');
    expect(redacted).toContain('debug=1');
    expect(redacted).not.toContain('secret123');
  });

  it('redacts all known auth query parameter names', () => {
    const cases = [
      'https://h/p?token=abc',
      'https://h/p?access_token=abc',
      'https://h/p?api_key=abc',
      'https://h/p?apikey=abc',
      'https://h/p?key=abc',
      'https://h/p?auth=abc',
      'https://h/p?secret=abc',
      'https://h/p?password=abc',
      'https://h/p?bearer=abc'
    ];
    for (const url of cases) {
      const redacted = redactAuthFromUrl(url);
      expect(redacted, `should redact ${url}`).not.toContain('abc');
      expect(redacted, `should still contain marker in ${url}`).toContain('***');
    }
  });

  it('matches auth parameter names case-insensitively', () => {
    expect(redactAuthFromUrl('https://h/p?Token=abc')).not.toContain('abc');
    expect(redactAuthFromUrl('https://h/p?TOKEN=abc')).not.toContain('abc');
    expect(redactAuthFromUrl('https://h/p?Access_Token=abc')).not.toContain('abc');
  });

  it('returns the URL unchanged when no auth parameter is present', () => {
    const url = 'wss://bridge.example.com/state?foo=bar&baz=qux';
    expect(redactAuthFromUrl(url)).toBe(url);
  });

  it('returns the URL unchanged when it cannot be parsed', () => {
    const garbage = 'not a url';
    expect(redactAuthFromUrl(garbage)).toBe(garbage);
  });

  it('handles URL with no query string', () => {
    expect(redactAuthFromUrl('wss://bridge.example.com/state')).toBe(
      'wss://bridge.example.com/state'
    );
  });

  it('redacts multiple auth parameters in the same URL', () => {
    const redacted = redactAuthFromUrl('https://h/p?token=abc&api_key=def&debug=1');
    expect(redacted).not.toContain('abc');
    expect(redacted).not.toContain('def');
    expect(redacted).toContain('debug=1');
  });
});
