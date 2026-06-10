<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { supabase, fetchTasks, type Task } from '$lib/supabase';
  import { config } from '$lib/config';
  import { fetchPRGates, type PRGateCheck } from '$lib/api/forgeClient';

  const REFRESH_MS = 30000;

  let tasks = $state<Task[]>([]);
  let loading = $state(true);
  let updating = $state(false);
  let collapsed = $state<Record<string, boolean>>({});
  let gateStatuses = $state<Record<number, PRGateCheck[] | null>>({});

  let phaseFilter = $state('all');
  let statusFilter = $state('all');
  let priorityFilter = $state('all');

  let phaseNames = $derived([...new Set(tasks.map((t) => t.phase))].sort());

  let filtered = $derived(
    tasks.filter((t) => {
      if (phaseFilter !== 'all' && t.phase !== phaseFilter) return false;
      if (statusFilter !== 'all' && t.status !== statusFilter) return false;
      if (priorityFilter !== 'all' && t.priority !== priorityFilter) return false;
      return true;
    })
  );

  let grouped = $derived.by(() => {
    const map: Record<string, Task[]> = {};
    for (const t of filtered) {
      const p = t.phase || '(no phase)';
      if (!map[p]) map[p] = [];
      map[p].push(t);
    }
    return Object.entries(map).sort(([a], [b]) => a.localeCompare(b));
  });

  function togglePhase(p: string) {
    collapsed[p] = !collapsed[p];
  }

  async function loadGateStatus(task: Task) {
    if (!task.pr_number || !config.useLiveBridge) return;
    const result = await fetchPRGates(task.pr_number);
    if (result.ok) {
      gateStatuses[task.pr_number] = result.data.gates;
    }
  }

  async function loadData() {
    if (!supabase) {
      loading = false;
      return;
    }
    tasks = await fetchTasks();
    if (config.useLiveBridge && tasks.length > 0) {
      await Promise.all(tasks.map(loadGateStatus));
    }
    loading = false;
    updating = false;
  }

  onMount(() => {
    const phaseParam = $page.url.searchParams.get('phase');
    if (phaseParam) phaseFilter = phaseParam;

    loadData();

    const intervalId = setInterval(async () => {
      updating = true;
      await loadData();
    }, REFRESH_MS);

    return () => clearInterval(intervalId);
  });

  function statusClass(s: string): string {
    switch (s) {
      case 'complete':
        return 'bg-signal-green/15 text-signal-green border-signal-green/25';
      case 'in_progress':
        return 'bg-accent-cyan/15 text-accent-cyan border-accent-cyan/25';
      case 'open':
        return 'bg-accent-amber/15 text-accent-amber border-accent-amber/25';
      default:
        return 'bg-text-muted/10 text-text-muted border-text-muted/20';
    }
  }

  function priorityClass(p: string): string {
    switch (p) {
      case 'high':
        return 'text-signal-red';
      case 'medium':
        return 'text-accent-amber';
      default:
        return 'text-text-muted';
    }
  }

  function counts(s: string): number {
    return tasks.filter((t) => t.status === s).length;
  }
</script>

<svelte:head>
  <title>AXIS - Tasks</title>
</svelte:head>

<div class="mx-auto flex h-full w-full max-w-[1100px] flex-col gap-5">
  {#if !supabase}
    <div
      class="flex flex-1 flex-col items-center justify-center gap-4 rounded-[20px] border border-hairline bg-bg-panel p-6 text-center"
    >
      <div
        class="flex h-12 w-12 items-center justify-center rounded-full border border-hairline bg-accent-amber/10 text-accent-amber"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke-width="1.5"
          stroke="currentColor"
          class="h-6 w-6"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z"
          />
        </svg>
      </div>
      <h2 class="font-mono text-lg font-bold tracking-widest text-text-primary uppercase">
        Supabase Not Configured
      </h2>
      <p class="max-w-sm text-xs text-text-muted">
        Set <span class="font-mono text-accent-cyan">PUBLIC_SUPABASE_URL</span> and
        <span class="font-mono text-accent-cyan">PUBLIC_SUPABASE_ANON_KEY</span> on Vercel to enable live
        task tracking.
      </p>
    </div>
  {:else if loading}
    <div
      class="flex flex-1 flex-col items-center justify-center gap-4 rounded-[20px] border border-hairline bg-bg-panel p-6 text-center"
    >
      <div
        class="h-12 w-12 animate-spin rounded-full border-2 border-hairline border-t-accent-cyan"
      ></div>
      <p class="font-mono text-xs text-text-muted">Loading tasks…</p>
    </div>
  {:else}
    <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex flex-wrap items-center gap-3">
        <h1 class="font-mono text-lg font-bold tracking-widest text-text-primary uppercase">
          Tasks
        </h1>
        {#if updating}
          <span
            class="rounded border border-accent-cyan/25 bg-accent-cyan/10 px-2 py-0.5 font-mono text-[9px] text-accent-cyan"
            >updating…</span
          >
        {:else}
          <span
            class="rounded border border-hairline bg-bg-panel px-2 py-0.5 font-mono text-[10px] text-text-muted"
            >{tasks.length} total</span
          >
        {/if}
      </div>
      <div class="flex flex-wrap items-center gap-2 font-mono text-[10px]">
        <span
          class="rounded border border-signal-green/25 bg-signal-green/10 px-2 py-1 text-signal-green"
          >{counts('complete')} done</span
        >
        <span
          class="rounded border border-accent-cyan/25 bg-accent-cyan/10 px-2 py-1 text-accent-cyan"
          >{counts('in_progress')} active</span
        >
        <span
          class="rounded border border-accent-amber/25 bg-accent-amber/10 px-2 py-1 text-accent-amber"
          >{counts('open')} open</span
        >
      </div>
    </div>

    <div
      class="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-[20px] border border-hairline bg-bg-panel p-3 sm:gap-3"
    >
      <span class="font-mono text-[10px] font-semibold tracking-wider text-text-muted uppercase"
        >Filter</span
      >
      <select
        bind:value={phaseFilter}
        class="cursor-pointer rounded-lg border border-hairline bg-bg-void px-2 py-1 font-mono text-[11px] text-text-primary outline-none focus:border-accent-cyan"
      >
        <option value="all">All Phases</option>
        {#each phaseNames as phase (phase)}
          <option value={phase}>{phase}</option>
        {/each}
      </select>
      <select
        bind:value={statusFilter}
        class="cursor-pointer rounded-lg border border-hairline bg-bg-void px-2 py-1 font-mono text-[11px] text-text-primary outline-none focus:border-accent-cyan"
      >
        <option value="all">All Statuses</option>
        <option value="open">Open</option>
        <option value="in_progress">In Progress</option>
        <option value="complete">Complete</option>
        <option value="pending">Pending</option>
      </select>
      <select
        bind:value={priorityFilter}
        class="cursor-pointer rounded-lg border border-hairline bg-bg-void px-2 py-1 font-mono text-[11px] text-text-primary outline-none focus:border-accent-cyan"
      >
        <option value="all">All Priorities</option>
        <option value="high">High</option>
        <option value="medium">Medium</option>
        <option value="low">Low</option>
      </select>
    </div>

    {#if filtered.length === 0}
      <div
        class="flex flex-1 flex-col items-center justify-center rounded-[20px] border border-hairline bg-bg-panel p-12 text-center"
      >
        <p class="font-mono text-xs text-text-muted">No tasks match the current filters.</p>
      </div>
    {:else}
      <div class="flex flex-1 scrollbar-thin flex-col gap-3 overflow-y-auto">
        {#each grouped as [phaseName, phaseTasks] (phaseName)}
          <div class="overflow-hidden rounded-[20px] border border-hairline bg-bg-panel">
            <button
              class="flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left transition hover:bg-white/[0.02]"
              onclick={() => togglePhase(phaseName)}
            >
              <div class="flex min-w-0 items-center gap-2">
                <span
                  class="truncate font-mono text-[11px] font-bold tracking-wider text-text-primary uppercase"
                  >{phaseName}</span
                >
                <span
                  class="shrink-0 rounded border border-hairline bg-bg-void px-1.5 py-px font-mono text-[8px] text-text-muted"
                  >{phaseTasks.length}</span
                >
              </div>
              <svg
                class="h-3 w-3 shrink-0 text-text-muted transition {collapsed[phaseName]
                  ? '-rotate-90'
                  : ''}"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="2"
                stroke="currentColor"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="m19.5 8.25-7.5 7.5-7.5-7.5"
                />
              </svg>
            </button>
            {#if !collapsed[phaseName]}
              <div class="divide-y divide-hairline/50">
                {#each phaseTasks as task (task.id)}
                  <div class="flex items-start gap-3 px-4 py-2.5 transition hover:bg-white/[0.02]">
                    <div class="min-w-0 flex-1">
                      <div class="flex items-center gap-2">
                        <span class="font-mono text-[13px] font-medium text-text-primary"
                          >{task.title}</span
                        >
                        <span
                          class="rounded border px-1.5 py-px font-mono text-[9px] uppercase {statusClass(
                            task.status
                          )}"
                        >
                          {task.status.replace('_', ' ')}
                        </span>
                        <span class="font-mono text-[9px] uppercase {priorityClass(task.priority)}">
                          {task.priority}
                        </span>
                      </div>
                      {#if task.description}
                        <p
                          class="mt-0.5 line-clamp-2 font-sans text-[11px] leading-relaxed text-text-muted"
                        >
                          {task.description}
                        </p>
                      {/if}
                      <div
                        class="mt-1.5 flex flex-wrap items-center gap-2.5 font-mono text-[9px] text-text-muted"
                      >
                        {#if task.owner}
                          <span>@{task.owner}</span>
                        {/if}
                        {#if task.gates_total > 0}
                          <span
                            class={task.gates_passed === task.gates_total
                              ? 'text-signal-green'
                              : 'text-accent-amber'}
                            >{task.gates_passed}/{task.gates_total} gates</span
                          >
                        {/if}
                      </div>
                      {#if task.pr_number && gateStatuses[task.pr_number]}
                        <div class="mt-1 flex items-center gap-2">
                          {#each gateStatuses[task.pr_number]! as gate (gate.name)}
                            <span
                              class="inline-flex items-center gap-0.5 font-mono text-[8px] {gate.passed
                                ? 'text-signal-green'
                                : 'text-text-muted/40'}"
                            >
                              {gate.name}
                              {#if gate.passed}<svg
                                  class="h-2.5 w-2.5"
                                  fill="none"
                                  viewBox="0 0 24 24"
                                  stroke-width="2.5"
                                  stroke="currentColor"
                                  ><path
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    d="m4.5 12.75 6 6 9-13.5"
                                  /></svg
                                >{:else}<svg
                                  class="h-2.5 w-2.5"
                                  fill="none"
                                  viewBox="0 0 24 24"
                                  stroke-width="2"
                                  stroke="currentColor"
                                  ><path
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    d="M6 18 18 6M6 6l12 12"
                                  /></svg
                                >{/if}
                            </span>
                          {/each}
                        </div>
                      {/if}
                    </div>
                    <div class="flex shrink-0 items-center gap-2">
                      {#if task.pr_number}
                        <a
                          href="https://github.com/{task.repo}/pull/{task.pr_number}"
                          target="_blank"
                          rel="noopener noreferrer"
                          class="rounded-lg border border-hairline bg-bg-void px-2 py-1 font-mono text-[9px] text-accent-cyan transition hover:bg-accent-cyan/10"
                        >
                          #{task.pr_number}
                        </a>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>
