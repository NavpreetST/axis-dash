<script lang="ts">
  import { onMount } from 'svelte';
  import { supabase, fetchTasks, type Task } from '$lib/supabase';

  let tasks = $state<Task[]>([]);
  let loading = $state(true);

  let phaseFilter = $state('all');
  let statusFilter = $state('all');
  let priorityFilter = $state('all');

  let phases = $derived([...new Set(tasks.map((t) => t.phase))].sort());

  let filtered = $derived(
    tasks.filter((t) => {
      if (phaseFilter !== 'all' && t.phase !== phaseFilter) return false;
      if (statusFilter !== 'all' && t.status !== statusFilter) return false;
      if (priorityFilter !== 'all' && t.priority !== priorityFilter) return false;
      return true;
    })
  );

  onMount(async () => {
    if (!supabase) {
      error =
        'Supabase credentials not configured — set PUBLIC_SUPABASE_URL and PUBLIC_SUPABASE_ANON_KEY.';
      loading = false;
      return;
    }
    tasks = await fetchTasks();
    loading = false;
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
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <h1 class="font-mono text-lg font-bold tracking-widest text-text-primary uppercase">
          Tasks
        </h1>
        <span
          class="rounded border border-hairline bg-bg-panel px-2 py-0.5 font-mono text-[10px] text-text-muted"
          >{tasks.length} total</span
        >
      </div>
      <div class="flex items-center gap-2 font-mono text-[10px]">
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
      class="flex flex-wrap items-center gap-3 rounded-[20px] border border-hairline bg-bg-panel p-4"
    >
      <span class="font-mono text-[10px] font-semibold tracking-wider text-text-muted uppercase"
        >Filter</span
      >
      <select
        bind:value={phaseFilter}
        class="cursor-pointer rounded-lg border border-hairline bg-bg-void px-2.5 py-1.5 font-mono text-[11px] text-text-primary outline-none focus:border-accent-cyan"
      >
        <option value="all">All Phases</option>
        {#each phases as phase (phase)}
          <option value={phase}>{phase}</option>
        {/each}
      </select>
      <select
        bind:value={statusFilter}
        class="cursor-pointer rounded-lg border border-hairline bg-bg-void px-2.5 py-1.5 font-mono text-[11px] text-text-primary outline-none focus:border-accent-cyan"
      >
        <option value="all">All Statuses</option>
        <option value="open">Open</option>
        <option value="in_progress">In Progress</option>
        <option value="complete">Complete</option>
        <option value="pending">Pending</option>
      </select>
      <select
        bind:value={priorityFilter}
        class="cursor-pointer rounded-lg border border-hairline bg-bg-void px-2.5 py-1.5 font-mono text-[11px] text-text-primary outline-none focus:border-accent-cyan"
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
      <div
        class="flex flex-1 scrollbar-thin flex-col gap-2 overflow-y-auto rounded-[20px] border border-hairline bg-bg-panel p-1"
      >
        {#each filtered as task (task.id)}
          <div class="flex items-start gap-3 rounded-xl px-4 py-3 transition hover:bg-white/[0.03]">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="font-mono text-[13px] font-medium text-text-primary">{task.title}</span
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
                {#if task.phase}
                  <span>{task.phase}</span>
                {/if}
                {#if task.owner}
                  <span>@{task.owner}</span>
                {/if}
                {#if task.gates_total > 0}
                  <span
                    class={task.gates_passed === task.gates_total
                      ? 'text-signal-green'
                      : 'text-accent-amber'}>{task.gates_passed}/{task.gates_total} gates</span
                  >
                {/if}
              </div>
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
  {/if}
</div>
