<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { supabase, fetchPhases, type Phase } from '$lib/supabase';

  const REFRESH_MS = 30000;

  let phases = $state<Phase[]>([]);
  let loading = $state(true);
  let updating = $state(false);

  let currentPhase = $derived(phases.find((p) => p.status === 'active'));

  async function loadData() {
    if (!supabase) {
      loading = false;
      return;
    }
    phases = await fetchPhases();
    loading = false;
    updating = false;
  }

  onMount(() => {
    loadData();

    const intervalId = setInterval(async () => {
      updating = true;
      await loadData();
    }, REFRESH_MS);

    return () => clearInterval(intervalId);
  });

  let collapsed = $state<Record<number, boolean>>({});

  function toggleCollapse(id: number) {
    collapsed[id] = !collapsed[id];
  }

  function goToPhase(title: string) {
    goto(`/todo?phase=${encodeURIComponent(title)}`);
  }

  function statusColor(s: string): string {
    switch (s) {
      case 'complete':
        return 'bg-signal-green';
      case 'active':
        return 'bg-accent-cyan';
      default:
        return 'bg-text-muted/30';
    }
  }

  function statusLabel(s: string): string {
    switch (s) {
      case 'complete':
        return 'Complete';
      case 'active':
        return 'Active';
      default:
        return 'Pending';
    }
  }

  function statusTextClass(s: string): string {
    switch (s) {
      case 'complete':
        return 'text-signal-green';
      case 'active':
        return 'text-accent-cyan';
      default:
        return 'text-text-muted';
    }
  }

  function progressColor(pct: number): string {
    if (pct >= 100) return 'bg-signal-green';
    if (pct > 0) return 'bg-accent-cyan';
    return 'bg-text-muted/20';
  }
</script>

<svelte:head>
  <title>AXIS - Roadmap</title>
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
        <span class="font-mono text-accent-cyan">PUBLIC_SUPABASE_ANON_KEY</span> on Vercel to enable the
        live roadmap.
      </p>
    </div>
  {:else if loading}
    <div
      class="flex flex-1 flex-col items-center justify-center gap-4 rounded-[20px] border border-hairline bg-bg-panel p-6 text-center"
    >
      <div
        class="h-12 w-12 animate-spin rounded-full border-2 border-hairline border-t-accent-cyan"
      ></div>
      <p class="font-mono text-xs text-text-muted">Loading roadmap…</p>
    </div>
  {:else if phases.length === 0}
    <div
      class="flex flex-1 flex-col items-center justify-center rounded-[20px] border border-hairline bg-bg-panel p-12 text-center"
    >
      <p class="font-mono text-xs text-text-muted">No phases found in Supabase.</p>
    </div>
  {:else}
    <div class="flex items-center gap-3">
      <h1 class="font-mono text-lg font-bold tracking-widest text-text-primary uppercase">
        Roadmap
      </h1>
      {#if updating}
        <span
          class="rounded border border-accent-cyan/25 bg-accent-cyan/10 px-2 py-0.5 font-mono text-[9px] text-accent-cyan"
          >updating…</span
        >
      {/if}
      {#if currentPhase}
        <span
          class="rounded border border-accent-cyan/25 bg-accent-cyan/10 px-2 py-0.5 font-mono text-[10px] text-accent-cyan"
        >
          Current: {currentPhase.title}
        </span>
      {/if}
    </div>

    <div class="flex flex-1 scrollbar-thin flex-col gap-2 overflow-y-auto">
      {#each phases as phase (phase.id)}
        <div
          class="cursor-pointer rounded-xl border bg-bg-panel p-3 transition hover:bg-white/[0.02]
          {phase.status === 'active' ? 'border-accent-cyan/25' : 'border-hairline'}"
          onclick={() => goToPhase(phase.title)}
          role="button"
          tabindex="0"
          onkeydown={(e) => e.key === 'Enter' && goToPhase(phase.title)}
        >
          <div class="flex items-center justify-between gap-2">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <div class="h-2 w-2 shrink-0 rounded-full {statusColor(phase.status)}"></div>
                <h2 class="truncate font-mono text-sm font-bold text-text-primary">
                  {phase.title}
                </h2>
                {#if phase.codename}
                  <span
                    class="hidden shrink-0 rounded border border-hairline bg-bg-void px-1 py-px font-mono text-[8px] text-text-muted sm:inline"
                    >{phase.codename}</span
                  >
                {/if}
                <span
                  class="shrink-0 font-mono text-[8px] uppercase {statusTextClass(phase.status)}"
                  >{statusLabel(phase.status)}</span
                >
              </div>

              {#if phase.headline && !collapsed[phase.id]}
                <p class="mt-1 truncate font-sans text-[10px] leading-snug text-text-muted">
                  {phase.headline}
                </p>
              {/if}

              {#if !collapsed[phase.id]}
                <div class="mt-2 flex items-center gap-3 font-mono text-[9px] text-text-muted">
                  {#if phase.timeline}
                    <span>{phase.timeline}</span>
                  {/if}
                  <div class="flex items-center gap-1">
                    <div class="h-1.5 w-20 overflow-hidden rounded-full bg-bg-void">
                      <div
                        class="h-full rounded-full transition-all duration-500 {progressColor(
                          phase.completion_pct
                        )}"
                        style="width: {Math.min(phase.completion_pct, 100)}%"
                      ></div>
                    </div>
                    <span
                      class={phase.completion_pct >= 100
                        ? 'text-signal-green'
                        : phase.completion_pct > 0
                          ? 'text-accent-cyan'
                          : 'text-text-muted'}>{phase.completion_pct}%</span
                    >
                  </div>
                </div>

                {#if phase.exit_criteria}
                  <details class="group mt-1.5">
                    <summary
                      class="cursor-pointer font-mono text-[8px] text-text-muted transition hover:text-text-primary"
                      onclick={(e) => e.stopPropagation()}
                      onkeydown={(e) => e.key === 'Enter' && e.stopPropagation()}
                    >
                      Exit criteria
                    </summary>
                    <p class="mt-0.5 font-sans text-[9px] leading-relaxed text-text-muted">
                      {phase.exit_criteria}
                    </p>
                  </details>
                {/if}
              {/if}
            </div>
            <button
              onclick={(e) => {
                e.stopPropagation();
                toggleCollapse(phase.id);
              }}
              onkeydown={(e) => {
                e.stopPropagation();
                if (e.key === 'Enter') toggleCollapse(phase.id);
              }}
              class="flex shrink-0 items-center justify-center rounded p-0.5 transition hover:bg-white/[0.05]"
              aria-label="Toggle phase details"
            >
              <svg
                class="h-3 w-3 text-text-muted transition {collapsed[phase.id] ? '-rotate-90' : ''}"
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
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
