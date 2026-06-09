<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { config } from '$lib/config';
  import {
    forge,
    forgeTasks,
    forgeSelectedId,
    forgeDetail,
    forgeDiffData,
    forgeGateResult,
    forgeConnStatus,
    forgeError,
    forgeLastPoll
  } from '$lib/stores/forge';

  let specInput = $state('');
  let submitting = $state(false);
  let actionBusy = $state(false);
  let submittedTaskId = $state<string | null>(null);

  const STATUS_COLORS: Record<string, string> = {
    pending: 'bg-accent-amber/10 text-accent-amber',
    running: 'bg-signal-blue/10 text-signal-blue',
    completed: 'bg-signal-green/10 text-signal-green',
    gated: 'bg-accent-cyan/10 text-accent-cyan',
    rejected: 'bg-signal-red/10 text-signal-red',
    failed: 'bg-signal-red/10 text-signal-red',
    unknown: 'bg-text-muted/10 text-text-muted'
  };

  const showDiff = $derived(
    $forgeDetail !== null &&
      ($forgeDetail.status === 'completed' || $forgeDetail.status === 'gated')
  );

  const showGate = $derived($forgeDetail !== null && $forgeDetail.status === 'completed');

  const canCleanup = $derived(
    $forgeDetail !== null && ['gated', 'rejected', 'failed'].includes($forgeDetail.status)
  );

  onMount(() => {
    if (config.useLiveBridge) {
      forge.loadTasks();
    }
  });

  onDestroy(() => {
    forge.reset();
  });

  $effect(() => {
    const detail = $forgeDetail;
    if (detail && submittedTaskId && detail.id === submittedTaskId) {
      submittedTaskId = null;
    }
  });

  async function handleSubmit() {
    const trimmed = specInput.trim();
    if (trimmed.length < 10 || submitting) return;
    submitting = true;
    submittedTaskId = null;
    try {
      const result = await forge.submitTask(trimmed);
      if (result !== null) {
        specInput = '';
        submittedTaskId = result;
      }
    } finally {
      submitting = false;
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleSubmit();
    }
  }

  async function runTaskAction(action: () => Promise<void>) {
    if (actionBusy) return;
    actionBusy = true;
    try {
      await action();
    } finally {
      actionBusy = false;
    }
  }

  function selectTask(id: string) {
    forge.selectTask(id);
  }
</script>

<div class="flex flex-col gap-3 rounded-[20px] border border-hairline bg-bg-panel p-5">
  <!-- Header -->
  <div class="flex items-center justify-between border-b border-hairline pb-2">
    <h2 class="font-sans text-xs font-semibold tracking-wider text-text-muted uppercase">
      Forge Tasks
    </h2>
    {#if $forgeConnStatus === 'loading'}
      <span class="font-mono text-[10px] text-accent-amber">loading…</span>
    {:else if $forgeConnStatus === 'error'}
      <span class="font-mono text-[10px] text-signal-red">error</span>
    {:else if $forgeConnStatus === 'live'}
      <span class="font-mono text-[10px] text-signal-green">{$forgeTasks.length} tasks</span>
    {/if}
  </div>

  <!-- Error banner -->
  {#if $forgeError}
    <div
      class="rounded-lg border border-signal-red/20 bg-signal-red/5 px-3 py-2 font-mono text-xs text-signal-red"
    >
      {$forgeError}
    </div>
  {/if}

  <!-- Submit form -->
  <div class="flex flex-col gap-2">
    <textarea
      bind:value={specInput}
      onkeydown={handleKeydown}
      placeholder="Describe the task for the forge agent (min 10 chars)…"
      rows="8"
      class="w-full resize-y rounded-lg border border-hairline bg-bg-void px-3 py-2 font-mono text-xs text-text-primary outline-none placeholder:text-text-muted focus:border-accent-cyan"
    ></textarea>
    <div class="flex items-center justify-between">
      <span class="font-mono text-[9px] text-text-muted">⌘/Ctrl+Enter to submit</span>
      <button
        type="button"
        onclick={handleSubmit}
        disabled={specInput.trim().length < 10 || submitting}
        class="cursor-pointer rounded-lg bg-accent-cyan px-3 py-1.5 font-mono text-[10px] font-semibold text-bg-void transition hover:bg-accent-cyan/80 disabled:cursor-not-allowed disabled:opacity-30"
      >
        {submitting ? 'submitting…' : 'submit'}
      </button>
    </div>
  </div>

  <!-- Submit feedback -->
  {#if submittedTaskId}
    {@const detail = $forgeDetail}
    {@const ts = $forgeLastPoll}
    <div
      class="flex flex-col gap-1.5 rounded-lg border border-accent-cyan/20 bg-accent-cyan/5 px-3 py-2 font-mono text-[10px]"
    >
      <div class="flex items-center justify-between">
        <span class="font-semibold text-accent-cyan">submitted</span>
        <span class="text-text-muted">id: {submittedTaskId.slice(0, 12)}</span>
      </div>
      {#if detail}
        <div class="flex items-center gap-2">
          <span
            class="rounded-sm px-1 py-px text-[9px] font-bold uppercase
              {STATUS_COLORS[detail.status] ?? STATUS_COLORS.unknown}"
          >
            {detail.status}
          </span>
          {#if ts}
            <span class="text-text-muted">updated {new Date(ts).toLocaleTimeString()}</span>
          {/if}
        </div>
        {#if detail.error}
          <div class="text-signal-red">error: {detail.error}</div>
        {/if}
        <div class="flex items-center gap-3 text-text-muted">
          <span
            >diff: {detail.status === 'completed' || detail.status === 'gated'
              ? 'ready'
              : 'pending'}</span
          >
          <span>gate: {detail.status === 'completed' ? 'available' : '—'}</span>
        </div>
      {:else if $forgeConnStatus === 'error'}
        <div class="text-signal-red">waiting for status…</div>
      {:else}
        <div class="text-text-muted">waiting for status…</div>
      {/if}
    </div>
  {/if}

  <!-- Task list + detail split -->
  <div class="flex min-h-[200px] gap-3">
    <!-- Task list (left) -->
    <div
      class="flex w-48 shrink-0 scrollbar-thin flex-col gap-1 overflow-y-auto border-r border-hairline pr-3"
    >
      {#if $forgeTasks.length === 0}
        <div class="flex flex-1 items-center justify-center font-mono text-[10px] text-text-muted">
          no tasks yet
        </div>
      {:else}
        {#each $forgeTasks as task (task.id)}
          <button
            type="button"
            onclick={() => selectTask(task.id)}
            class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-left font-mono text-[10px] transition hover:bg-white/5
              {$forgeSelectedId === task.id
              ? 'border border-accent-cyan/20 bg-accent-cyan/10'
              : 'border border-transparent'}"
          >
            <span
              class="shrink-0 rounded-sm px-1 py-px text-center text-[8px] font-bold uppercase
                {STATUS_COLORS[task.status] ?? STATUS_COLORS.unknown}"
            >
              {task.status}
            </span>
            <span class="truncate text-text-primary">{task.id.slice(0, 8)}</span>
          </button>
        {/each}
      {/if}
    </div>

    <!-- Task detail (right) -->
    <div class="flex min-w-0 flex-1 flex-col gap-3">
      {#if !$forgeSelectedId}
        <div class="flex flex-1 items-center justify-center font-mono text-[10px] text-text-muted">
          select a task to view details
        </div>
      {:else if !$forgeDetail && $forgeConnStatus !== 'error'}
        <div class="flex flex-1 items-center justify-center font-mono text-[10px] text-text-muted">
          loading task…
        </div>
      {:else if $forgeDetail}
        <!-- Status bar -->
        <div class="flex items-center gap-3">
          <span
            class="rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase
              {STATUS_COLORS[$forgeDetail.status] ?? STATUS_COLORS.unknown}"
          >
            {$forgeDetail.status}
          </span>
          <span class="font-mono text-[9px] text-text-muted">
            id: {$forgeDetail.id.slice(0, 12)}
          </span>
          {#if $forgeDetail.error}
            <span class="font-mono text-[9px] text-signal-red">
              error: {$forgeDetail.error}
            </span>
          {/if}
        </div>

        <!-- Spec -->
        <div class="rounded-lg border border-hairline bg-bg-void p-2">
          <div class="mb-1 font-mono text-[8px] text-text-muted uppercase">spec</div>
          <div class="font-mono text-xs text-text-primary">{$forgeDetail.spec}</div>
        </div>

        <!-- Diff viewer -->
        {#if showDiff && $forgeDiffData}
          {#if $forgeDiffData.diffs.length === 0}
            <div class="font-mono text-[10px] text-text-muted">no file changes</div>
          {:else}
            <div class="flex max-h-60 scrollbar-thin flex-col gap-2 overflow-y-auto">
              {#each $forgeDiffData.diffs as file (file.path)}
                <div class="rounded-lg border border-hairline bg-bg-void">
                  <div class="flex items-center justify-between border-b border-hairline px-2 py-1">
                    <span class="font-mono text-[10px] text-text-primary">{file.path}</span>
                    <span class="font-mono text-[9px] text-text-muted">
                      <span class="text-signal-green">+{file.additions}</span>
                      <span class="text-signal-red">-{file.deletions}</span>
                    </span>
                  </div>
                  <pre
                    class="overflow-x-auto p-2 font-mono text-[9px] leading-relaxed text-text-primary">{file.patch}</pre>
                </div>
              {/each}
            </div>
          {/if}

          {#if $forgeDiffData.logs.length > 0}
            <div class="rounded-lg border border-hairline bg-bg-void p-2">
              <div class="mb-1 font-mono text-[8px] text-text-muted uppercase">logs</div>
              <pre
                class="max-h-32 scrollbar-thin overflow-y-auto font-mono text-[9px] text-text-muted">{$forgeDiffData.logs.join(
                  '\n'
                )}</pre>
            </div>
          {/if}
        {:else if showDiff}
          <button
            type="button"
            onclick={() => forge.loadDiff($forgeDetail!.id)}
            class="cursor-pointer self-start rounded-lg border border-hairline px-3 py-1.5 font-mono text-[10px] text-text-muted transition hover:bg-white/5"
          >
            load diff
          </button>
        {/if}

        <!-- Gate controls -->
        {#if showGate}
          <div class="flex items-center gap-2 border-t border-hairline pt-2">
            <span class="font-mono text-[9px] text-text-muted">gate:</span>
            <button
              type="button"
              onclick={() => runTaskAction(() => forge.approveGate($forgeDetail!.id))}
              disabled={actionBusy}
              class="cursor-pointer rounded-lg bg-signal-green/15 px-3 py-1.5 font-mono text-[10px] font-semibold text-signal-green transition hover:bg-signal-green/25 disabled:cursor-not-allowed disabled:opacity-30"
            >
              approve
            </button>
            <button
              type="button"
              onclick={() => runTaskAction(() => forge.rejectGate($forgeDetail!.id))}
              disabled={actionBusy}
              class="cursor-pointer rounded-lg bg-signal-red/15 px-3 py-1.5 font-mono text-[10px] font-semibold text-signal-red transition hover:bg-signal-red/25 disabled:cursor-not-allowed disabled:opacity-30"
            >
              reject
            </button>
          </div>
        {/if}

        <!-- Gate result -->
        {#if $forgeGateResult}
          <div
            class="rounded-lg border px-2 py-1.5 font-mono text-[10px]
              {$forgeGateResult.overall_passed
              ? 'border-signal-green/20 bg-signal-green/5 text-signal-green'
              : 'border-signal-red/20 bg-signal-red/5 text-signal-red'}"
          >
            gate: {$forgeGateResult.overall_passed ? 'PASSED' : 'FAILED'} (lint: {$forgeGateResult.lint_passed
              ? '✓'
              : '✗'}, test: {$forgeGateResult.test_passed ? '✓' : '✗'}, build: {$forgeGateResult.build_passed
              ? '✓'
              : '✗'})
            {#if $forgeGateResult.errors.length > 0}
              <div class="mt-1 text-signal-red">{$forgeGateResult.errors.join('; ')}</div>
            {/if}
          </div>
        {/if}

        <!-- Cleanup -->
        {#if canCleanup}
          <button
            type="button"
            onclick={() => runTaskAction(() => forge.cleanupTask($forgeDetail!.id))}
            disabled={actionBusy}
            class="cursor-pointer self-start rounded-lg border border-hairline px-3 py-1.5 font-mono text-[10px] text-text-muted transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-30"
          >
            cleanup
          </button>
        {/if}
      {/if}
    </div>
  </div>
</div>
