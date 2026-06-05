<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { telemetry, logs } from '$lib';

  // Start the store loops on mount
  onMount(() => {
    telemetry.start();
    logs.start();
  });

  onDestroy(() => {
    telemetry.stop();
    logs.stop();
  });

  // Helper to format uptime seconds into h, m, s
  function formatUptime(seconds: number): string {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h}h ${m}m ${s}s`;
  }
</script>

<svelte:head>
  <title>AXIS - Cockpit</title>
</svelte:head>

{#if !$telemetry.connected}
  <div
    class="flex flex-1 flex-col items-center justify-center rounded-[20px] border border-hairline bg-bg-panel p-12 transition-all"
  >
    <div
      class="mb-4 h-16 w-16 animate-spin rounded-full border-2 border-dashed border-signal-red"
    ></div>
    <h2 class="font-mono text-lg font-bold tracking-widest text-signal-red uppercase">
      Aegis Daemon Offline
    </h2>
    <p class="mt-2 max-w-md text-center font-sans text-sm text-text-muted">
      Connection to the AI execution surface has been severed. Reconnect the daemon to restore
      real-time telemetry pipelines.
    </p>
  </div>
{:else}
  <!-- Main Grid Content -->
  <div class="flex h-full flex-col gap-6">
    <!-- KPI Cards Row -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <div class="flex flex-col gap-1 rounded-[20px] border border-hairline bg-bg-panel p-5">
        <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase">Uptime</span>
        <span class="font-mono text-xl font-bold text-accent-cyan"
          >{formatUptime($telemetry.uptime_seconds)}</span
        >
        <span class="font-sans text-[10px] text-text-muted">since last restart</span>
      </div>

      <div class="flex flex-col gap-1 rounded-[20px] border border-hairline bg-bg-panel p-5">
        <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase">Tick Rate</span
        >
        <span class="font-mono text-xl font-bold text-text-primary"
          >{$telemetry.tick_rate} <span class="text-xs text-text-muted">tick/s</span></span
        >
        <span class="font-sans text-[10px] text-text-muted">rolling 60s avg</span>
      </div>

      <div class="flex flex-col gap-1 rounded-[20px] border border-hairline bg-bg-panel p-5">
        <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase"
          >PAM Coherence</span
        >
        <span
          class="font-mono text-xl font-bold {$telemetry.pam >= 0.9
            ? 'text-signal-green'
            : $telemetry.pam >= 0.83
              ? 'text-accent-amber'
              : 'text-signal-red'}">{$telemetry.pam}</span
        >
        <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-hairline">
          <div
            class="h-full rounded-full transition-all duration-300 {$telemetry.pam >= 0.9
              ? 'bg-signal-green'
              : $telemetry.pam >= 0.83
                ? 'bg-accent-amber'
                : 'bg-signal-red'}"
            style="width: {$telemetry.pam * 100}%"
          ></div>
        </div>
      </div>

      <div class="flex flex-col gap-1 rounded-[20px] border border-hairline bg-bg-panel p-5">
        <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase">RPD Usage</span
        >
        <span class="font-mono text-xl font-bold text-accent-amber"
          >{$telemetry.rpd_used}
          <span class="text-xs text-text-muted">/ {$telemetry.rpd_budget}</span></span
        >
        <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-hairline">
          <div
            class="h-full rounded-full bg-accent-amber"
            style="width: {$telemetry.rpd_budget > 0
              ? Math.min(100, ($telemetry.rpd_used / $telemetry.rpd_budget) * 100)
              : 0}%"
          ></div>
        </div>
      </div>
    </div>

    <!-- Signal State (Hero Panel) -->
    <div class="flex flex-1 flex-col gap-4 rounded-[20px] border border-hairline bg-bg-panel p-6">
      <div class="flex items-center justify-between border-b border-hairline pb-2">
        <h2 class="font-sans text-xs font-semibold tracking-wider text-text-muted uppercase">
          NeuroBus Signal State
        </h2>
        <span class="font-mono text-[10px] text-accent-cyan"
          >Active Renderer: {$telemetry.provider}</span
        >
      </div>

      <div class="grid flex-1 grid-cols-1 items-center gap-6 md:grid-cols-2">
        {#each Object.entries($telemetry.neurobus) as [key, val] (key)}
          <div class="flex flex-col gap-2">
            <div class="flex justify-between font-mono text-xs">
              <span class="text-text-muted capitalize">{key}</span>
              <span class="text-text-primary">{val}</span>
            </div>
            <div class="h-2.5 w-full overflow-hidden rounded-full bg-hairline">
              <div
                class="h-full rounded-full transition-all duration-500
                  {key === 'reward' ? 'bg-accent-amber' : ''}
                  {key === 'novelty' ? 'bg-signal-blue' : ''}
                  {key === 'attention' ? 'bg-text-primary' : ''}
                  {key === 'patience' ? 'bg-accent-violet' : ''}
                  {key === 'threat' ? 'bg-signal-red' : ''}
                  {key === 'trust' ? 'bg-signal-green' : ''}
                "
                style="width: {val * 100}%"
              ></div>
            </div>
          </div>
        {/each}
      </div>
    </div>

    <!-- Live Log Panel -->
    <div class="flex h-60 flex-col gap-2 rounded-[20px] border border-hairline bg-bg-panel p-6">
      <div class="flex items-center justify-between border-b border-hairline pb-2">
        <h2 class="font-sans text-xs font-semibold tracking-wider text-text-muted uppercase">
          Live System Logs
        </h2>
        <span class="font-mono text-[10px] text-text-muted">stream: /var/helios/aegis.log</span>
      </div>
      <div class="flex flex-1 scrollbar-thin flex-col gap-1 overflow-y-auto pr-2 font-mono text-xs">
        {#each $logs as log, idx (`${log.timestamp}-${log.source}-${log.message}-${idx}`)}
          <div class="flex gap-3 rounded p-0.5 leading-relaxed transition hover:bg-white/5">
            <span class="shrink-0 text-text-muted">{log.timestamp}</span>
            <span
              class="w-12 shrink-0 rounded-sm px-1 text-center text-[10px] font-bold uppercase
              {log.source === 'tick' ? 'bg-signal-blue/10 text-signal-blue' : ''}
              {log.source === 'mem' ? 'bg-accent-violet/10 text-accent-violet' : ''}
              {log.source === 'sys' ? 'bg-accent-cyan/10 text-accent-cyan' : ''}
              {log.source === 'task' ? 'bg-accent-amber/10 text-accent-amber' : ''}
            ">[{log.source}]</span
            >
            <span
              class="
              {log.type === 'error' ? 'text-signal-red' : ''}
              {log.type === 'warning' ? 'text-accent-amber' : ''}
              {log.type === 'success' ? 'text-signal-green' : ''}
              {log.type === 'info' ? 'text-text-primary' : ''}
            ">{log.message}</span
            >
          </div>
        {/each}
      </div>
    </div>
  </div>
{/if}

<style>
  /* Scrollbar styles */
  .scrollbar-thin::-webkit-scrollbar {
    width: 4px;
    height: 4px;
  }
  .scrollbar-thin::-webkit-scrollbar-track {
    background: transparent;
  }
  .scrollbar-thin::-webkit-scrollbar-thumb {
    background: var(--color-hairline);
    border-radius: 4px;
  }
  .scrollbar-thin::-webkit-scrollbar-thumb:hover {
    background: var(--color-text-muted);
  }
</style>
