import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import {
  forgeSubmit,
  forgeList,
  forgeStatus,
  forgeDiff,
  forgeGate,
  forgeCleanup
} from './forgeClient';

// ---------------------------------------------------------------------------
// Mock fetchWithAuth — the forge client imports it from $lib/api/client
// We mock the module so all internal calls hit our fake fetch.
// ---------------------------------------------------------------------------

const mockFetch = vi.fn<(input: string | URL | Request, init?: RequestInit) => Promise<Response>>();

vi.mock('$lib/api/client', () => ({
  fetchWithAuth: (...args: Parameters<typeof mockFetch>) => mockFetch(...args),
  buildHttpUrl: (path: string) => `https://bridge.test${path}`,
  getToken: () => 'test-token',
  applyAuthToUrl: (url: string) => url
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' }
  });
}

function errorResponse(detail: string, status = 400): Response {
  return jsonResponse({ detail }, status);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('forgeClient', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // --- forgeSubmit ----------------------------------------------------------

  describe('forgeSubmit', () => {
    it('sends POST /forge/submit with spec in body', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ task_id: 'abc-123' }));

      const result = await forgeSubmit('add a new login button');

      expect(mockFetch).toHaveBeenCalledOnce();
      const [url, init] = mockFetch.mock.calls[0]!;
      expect(url).toContain('/forge/submit');
      expect(init?.method).toBe('POST');
      expect(JSON.parse(init!.body as string)).toEqual({ spec: 'add a new login button' });
      expect(result).toEqual({ ok: true, data: { task_id: 'abc-123' } });
    });

    it('returns error detail on non-2xx', async () => {
      mockFetch.mockResolvedValueOnce(errorResponse('spec must be >= 10 chars', 400));

      const result = await forgeSubmit('short');

      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.status).toBe(400);
        expect(result.detail).toBe('spec must be >= 10 chars');
      }
    });

    it('returns error on network failure', async () => {
      mockFetch.mockRejectedValueOnce(new Error('network down'));

      const result = await forgeSubmit('test spec for network failure');

      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.status).toBe(0);
        expect(result.detail).toContain('network down');
      }
    });
  });

  // --- forgeList -----------------------------------------------------------

  describe('forgeList', () => {
    it('sends GET /forge/list and returns task array', async () => {
      const tasks = [
        { id: 't1', status: 'pending' },
        { id: 't2', status: 'completed' }
      ];
      mockFetch.mockResolvedValueOnce(jsonResponse(tasks));

      const result = await forgeList();

      expect(mockFetch).toHaveBeenCalledOnce();
      expect(mockFetch.mock.calls[0]![0]).toContain('/forge/list');
      expect(result).toEqual({ ok: true, data: tasks });
    });

    it('returns empty array when no tasks exist', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse([]));

      const result = await forgeList();

      expect(result).toEqual({ ok: true, data: [] });
    });

    it('returns error on bridge failure', async () => {
      mockFetch.mockResolvedValueOnce(errorResponse('forge not initialized', 503));

      const result = await forgeList();

      expect(result.ok).toBe(false);
    });

    it('keeps HTTP status when non-2xx JSON payload is null', async () => {
      mockFetch.mockResolvedValueOnce(
        new Response('null', {
          status: 500,
          headers: { 'Content-Type': 'application/json' }
        })
      );

      const result = await forgeList();

      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.status).toBe(500);
        expect(result.detail).toBeTruthy();
      }
    });

    it('keeps HTTP status when non-2xx JSON payload is a string', async () => {
      mockFetch.mockResolvedValueOnce(
        new Response('"internal error"', {
          status: 502,
          headers: { 'Content-Type': 'application/json' }
        })
      );

      const result = await forgeList();

      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.status).toBe(502);
        expect(result.detail).toBeTruthy();
      }
    });
  });

  // --- forgeStatus ---------------------------------------------------------

  describe('forgeStatus', () => {
    it('sends GET /forge/{id}/status with encoded task id', async () => {
      const detail = {
        id: 'task-abc',
        spec: 'fix the bug',
        status: 'running',
        workdir: '/tmp/forge/task-abc',
        created_at: 1000,
        completed_at: null,
        error: null,
        gate_result: null
      };
      mockFetch.mockResolvedValueOnce(jsonResponse(detail));

      const result = await forgeStatus('task-abc');

      expect(mockFetch.mock.calls[0]![0]).toContain('/forge/task-abc/status');
      expect(result).toEqual({ ok: true, data: detail });
    });

    it('returns 404 for unknown task', async () => {
      mockFetch.mockResolvedValueOnce(errorResponse('unknown task xyz', 404));

      const result = await forgeStatus('xyz');

      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.status).toBe(404);
      }
    });
  });

  // --- forgeDiff -----------------------------------------------------------

  describe('forgeDiff', () => {
    it('sends GET /forge/{id}/diff and returns diffs + logs', async () => {
      const diffResult = {
        diffs: [
          {
            path: 'src/app.ts',
            additions: 10,
            deletions: 3,
            patch: '+new line\n-old line'
          }
        ],
        logs: ['lint passed', 'tests passed']
      };
      mockFetch.mockResolvedValueOnce(jsonResponse(diffResult));

      const result = await forgeDiff('task-abc');

      expect(mockFetch.mock.calls[0]![0]).toContain('/forge/task-abc/diff');
      expect(result).toEqual({ ok: true, data: diffResult });
    });
  });

  // --- forgeGate -----------------------------------------------------------

  describe('forgeGate', () => {
    it('sends POST /forge/{id}/gate with approve=true', async () => {
      const gateResult = {
        overall_passed: true,
        lint_passed: true,
        test_passed: true,
        build_passed: true,
        errors: []
      };
      mockFetch.mockResolvedValueOnce(jsonResponse(gateResult));

      const result = await forgeGate('task-abc', true);

      const [url, init] = mockFetch.mock.calls[0]!;
      expect(url).toContain('/forge/task-abc/gate');
      expect(init?.method).toBe('POST');
      expect(JSON.parse(init!.body as string)).toEqual({ approve: true });
      expect(result).toEqual({ ok: true, data: gateResult });
    });

    it('sends POST /forge/{id}/gate with approve=false (reject)', async () => {
      const gateResult = {
        overall_passed: false,
        lint_passed: true,
        test_passed: false,
        build_passed: true,
        errors: ['tests failed']
      };
      mockFetch.mockResolvedValueOnce(jsonResponse(gateResult));

      const result = await forgeGate('task-abc', false);

      const [, init] = mockFetch.mock.calls[0]!;
      expect(JSON.parse(init!.body as string)).toEqual({ approve: false });
      expect(result.ok).toBe(true);
      if (result.ok) {
        expect(result.data.overall_passed).toBe(false);
      }
    });

    it('returns error on invalid body', async () => {
      mockFetch.mockResolvedValueOnce(errorResponse('approve must be boolean', 400));

      const result = await forgeGate('task-abc', true);

      expect(result.ok).toBe(false);
    });
  });

  // --- forgeCleanup --------------------------------------------------------

  describe('forgeCleanup', () => {
    it('sends POST /forge/{id}/cleanup and returns message', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ message: 'cleaned up task abc' }));

      const result = await forgeCleanup('task-abc');

      const [url, init] = mockFetch.mock.calls[0]!;
      expect(url).toContain('/forge/task-abc/cleanup');
      expect(init?.method).toBe('POST');
      expect(result).toEqual({ ok: true, data: { message: 'cleaned up task abc' } });
    });

    it('returns error for unknown task', async () => {
      mockFetch.mockResolvedValueOnce(errorResponse('unknown task xyz', 400));

      const result = await forgeCleanup('xyz');

      expect(result.ok).toBe(false);
    });
  });

  // --- URL encoding --------------------------------------------------------

  describe('URL encoding', () => {
    it('encodes special characters in task IDs', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ status: 'running' }));

      await forgeStatus('task/with/slashes');

      expect(mockFetch.mock.calls[0]![0]).toContain(encodeURIComponent('task/with/slashes'));
    });
  });
});
