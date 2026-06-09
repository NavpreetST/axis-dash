import { writable, derived, get } from 'svelte/store';
import {
  forgeList,
  forgeSubmit,
  forgeStatus,
  forgeDiff,
  forgeGate,
  forgeCleanup,
  type ForgeTaskSummary,
  type ForgeTaskDetail,
  type ForgeDiffResult,
  type GateResult
} from '$lib/api/forgeClient';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ForgeConnectionStatus = 'idle' | 'loading' | 'live' | 'error';

export interface ForgeState {
  tasks: ForgeTaskSummary[];
  selectedTaskId: string | null;
  detail: ForgeTaskDetail | null;
  diff: ForgeDiffResult | null;
  gateResult: GateResult | null;
  status: ForgeConnectionStatus;
  error: string | null;
  lastPollAt: number | null;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

const INITIAL_STATE: ForgeState = {
  tasks: [],
  selectedTaskId: null,
  detail: null,
  diff: null,
  gateResult: null,
  status: 'idle',
  error: null,
  lastPollAt: null
};

function createForgeStore() {
  const { subscribe, update, set } = writable<ForgeState>(INITIAL_STATE);

  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  const POLL_INTERVAL = 2000;

  // --- helpers ---------------------------------------------------------------

  function setError(msg: string | null) {
    update((s) => ({ ...s, error: msg, status: msg ? 'error' : 'live' }));
  }

  function clearPoll() {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  const POLLABLE = new Set(['pending', 'running']);

  function schedulePoll(taskId: string) {
    clearPoll();
    pollTimer = setTimeout(async () => {
      await refreshStatus(taskId);
      const cur = get({ subscribe });
      if (cur.detail && POLLABLE.has(cur.detail.status)) {
        schedulePoll(taskId);
      }
    }, POLL_INTERVAL);
  }

  // --- public API -----------------------------------------------------------

  async function loadTasks() {
    update((s) => ({ ...s, status: 'loading', error: null }));
    const res = await forgeList();
    if (!res.ok) {
      setError(res.detail);
      return;
    }
    update((s) => ({ ...s, tasks: res.data, status: 'live', error: null }));
  }

  async function submitTask(spec: string) {
    update((s) => ({ ...s, error: null }));
    const res = await forgeSubmit(spec);
    if (!res.ok) {
      setError(res.detail);
      return null;
    }
    const taskId = res.data.task_id;
    // Optimistically add to list
    update((s) => ({
      ...s,
      tasks: [...s.tasks, { id: taskId, status: 'pending' }],
      selectedTaskId: taskId,
      detail: null,
      diff: null,
      gateResult: null,
      lastPollAt: null
    }));
    // Start polling
    await refreshStatus(taskId);
    schedulePoll(taskId);
    return taskId;
  }

  async function refreshStatus(taskId: string) {
    const res = await forgeStatus(taskId);
    if (!res.ok) {
      setError(res.detail);
      return;
    }
    update((s) => ({
      ...s,
      detail: res.data,
      error: null,
      lastPollAt: Date.now(),
      // Also update the summary in the list
      tasks: s.tasks.map((t) => (t.id === taskId ? { ...t, status: res.data.status } : t))
    }));
  }

  async function loadDiff(taskId: string) {
    update((s) => ({ ...s, error: null }));
    const res = await forgeDiff(taskId);
    if (!res.ok) {
      setError(res.detail);
      return;
    }
    update((s) => ({ ...s, diff: res.data, error: null }));
  }

  async function approveGate(taskId: string) {
    update((s) => ({ ...s, error: null }));
    const res = await forgeGate(taskId, true);
    if (!res.ok) {
      setError(res.detail);
      return;
    }
    update((s) => ({ ...s, gateResult: res.data, error: null }));
    // Refresh status to pick up state change
    await refreshStatus(taskId);
  }

  async function rejectGate(taskId: string) {
    update((s) => ({ ...s, error: null }));
    const res = await forgeGate(taskId, false);
    if (!res.ok) {
      setError(res.detail);
      return;
    }
    update((s) => ({ ...s, gateResult: res.data, error: null }));
    await refreshStatus(taskId);
  }

  async function cleanupTask(taskId: string) {
    update((s) => ({ ...s, error: null }));
    const res = await forgeCleanup(taskId);
    if (!res.ok) {
      setError(res.detail);
      return;
    }
    // Remove from list and deselect
    update((s) => ({
      ...s,
      tasks: s.tasks.filter((t) => t.id !== taskId),
      selectedTaskId: s.selectedTaskId === taskId ? null : s.selectedTaskId,
      detail: s.selectedTaskId === taskId ? null : s.detail,
      diff: s.selectedTaskId === taskId ? null : s.diff,
      gateResult: s.selectedTaskId === taskId ? null : s.gateResult,
      error: null
    }));
  }

  async function selectTask(taskId: string | null) {
    clearPoll();
    update((s) => ({
      ...s,
      selectedTaskId: taskId,
      detail: null,
      diff: null,
      gateResult: null,
      error: null,
      lastPollAt: null
    }));
    if (taskId) {
      await refreshStatus(taskId);
      const cur = get({ subscribe });
      if (cur.detail && POLLABLE.has(cur.detail.status)) {
        schedulePoll(taskId);
      }
    }
  }

  function reset() {
    clearPoll();
    set(INITIAL_STATE);
  }

  return {
    subscribe,
    loadTasks,
    submitTask,
    refreshStatus,
    loadDiff,
    approveGate,
    rejectGate,
    cleanupTask,
    selectTask,
    reset
  };
}

export const forge = createForgeStore();

// ---------------------------------------------------------------------------
// Derived helpers for template convenience
// ---------------------------------------------------------------------------

export const forgeTasks = derived(forge, ($f) => $f.tasks);
export const forgeSelectedId = derived(forge, ($f) => $f.selectedTaskId);
export const forgeDetail = derived(forge, ($f) => $f.detail);
export const forgeDiffData = derived(forge, ($f) => $f.diff);
export const forgeGateResult = derived(forge, ($f) => $f.gateResult);
export const forgeConnStatus = derived(forge, ($f) => $f.status);
export const forgeError = derived(forge, ($f) => $f.error);
export const forgeLastPoll = derived(forge, ($f) => $f.lastPollAt);
