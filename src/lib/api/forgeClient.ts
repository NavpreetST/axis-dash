import { fetchWithAuth, buildHttpUrl } from '$lib/api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ForgeTaskStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'gated'
  | 'rejected'
  | 'failed'
  | 'unknown';

export interface ForgeTaskSummary {
  id: string;
  status: ForgeTaskStatus;
}

export interface ForgeTaskDetail {
  id: string;
  spec: string;
  status: ForgeTaskStatus;
  workdir: string;
  created_at: number;
  completed_at: number | null;
  error: string | null;
  gate_result: GateResult | null;
  pr_number?: number | null;
  repo?: string;
}

export interface ForgeDiffFile {
  path: string;
  additions: number;
  deletions: number;
  patch: string;
}

export interface ForgeDiffResult {
  diffs: ForgeDiffFile[];
  logs: string[];
}

export interface GateResult {
  overall_passed: boolean;
  lint_passed: boolean;
  test_passed: boolean;
  build_passed: boolean;
  errors: string[];
}

export interface ForgeSubmitResponse {
  task_id: string;
}

export interface ForgeCleanupResponse {
  message: string;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

type HttpError = { ok: false; status: number; detail: string };
type HttpOk<T> = { ok: true; data: T };
type HttpResult<T> = HttpOk<T> | HttpError;

async function httpGet<T>(path: string): Promise<HttpResult<T>> {
  try {
    const res = await fetchWithAuth(buildHttpUrl(path), { method: 'GET' });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      const detail =
        typeof body === 'object' && body !== null && 'detail' in body
          ? String(body.detail)
          : res.statusText || `HTTP ${res.status}`;
      return { ok: false, status: res.status, detail };
    }
    const data = (await res.json()) as T;
    return { ok: true, data };
  } catch (e) {
    return { ok: false, status: 0, detail: e instanceof Error ? e.message : String(e) };
  }
}

async function httpPost<T>(path: string, body?: unknown): Promise<HttpResult<T>> {
  try {
    const init: RequestInit = { method: 'POST' };
    if (body !== undefined) {
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    const res = await fetchWithAuth(buildHttpUrl(path), init);
    if (!res.ok) {
      const b = await res.json().catch(() => null);
      const detail =
        typeof b === 'object' && b !== null && 'detail' in b
          ? String(b.detail)
          : res.statusText || `HTTP ${res.status}`;
      return { ok: false, status: res.status, detail };
    }
    const data = (await res.json()) as T;
    return { ok: true, data };
  } catch (e) {
    return { ok: false, status: 0, detail: e instanceof Error ? e.message : String(e) };
  }
}

// ---------------------------------------------------------------------------
// Public API — mirrors the 6 bridge routes 1:1
// ---------------------------------------------------------------------------

/** POST /forge/submit  { spec }  → { task_id } */
export async function forgeSubmit(spec: string): Promise<HttpResult<ForgeSubmitResponse>> {
  return httpPost<ForgeSubmitResponse>('/forge/submit', { spec });
}

/** GET /forge/list  → [ { id, status } ] */
export async function forgeList(): Promise<HttpResult<ForgeTaskSummary[]>> {
  return httpGet<ForgeTaskSummary[]>('/forge/list');
}

/** GET /forge/{id}/status  → ForgeTaskDetail */
export async function forgeStatus(taskId: string): Promise<HttpResult<ForgeTaskDetail>> {
  return httpGet<ForgeTaskDetail>(`/forge/${encodeURIComponent(taskId)}/status`);
}

/** GET /forge/{id}/diff  → { diffs, logs } */
export async function forgeDiff(taskId: string): Promise<HttpResult<ForgeDiffResult>> {
  return httpGet<ForgeDiffResult>(`/forge/${encodeURIComponent(taskId)}/diff`);
}

/** POST /forge/{id}/gate  { approve }  → GateResult */
export async function forgeGate(taskId: string, approve: boolean): Promise<HttpResult<GateResult>> {
  return httpPost<GateResult>(`/forge/${encodeURIComponent(taskId)}/gate`, { approve });
}

/** POST /forge/{id}/cleanup  → { message } */
export async function forgeCleanup(taskId: string): Promise<HttpResult<ForgeCleanupResponse>> {
  return httpPost<ForgeCleanupResponse>(`/forge/${encodeURIComponent(taskId)}/cleanup`);
}

// ---------------------------------------------------------------------------
// Gate status per PR
// ---------------------------------------------------------------------------

export interface PRGateCheck {
  name: string;
  passed: boolean;
}

export interface PRGateStatus {
  pr_number: number;
  gates: PRGateCheck[];
}

/** GET /api/gates?pr_number=N  → { pr_number, gates: [...] } */
export async function fetchPRGates(prNumber: number): Promise<HttpResult<PRGateStatus>> {
  return httpGet<PRGateStatus>(`/api/gates?pr_number=${prNumber}`);
}
