<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import {
    logs,
    NeuroBusPanel,
    KpiStrip,
    RuntimePanel,
    ActivityPanel,
    ForgePanel,
    telemetry
  } from '$lib';
  import { config } from '$lib/config';

  onMount(() => {
    if (!config.useLiveBridge) {
      logs.start();
    }
  });

  onDestroy(() => {
    logs.stop();
  });
</script>

<svelte:head>
  <title>AXIS - Cockpit</title>
</svelte:head>

<!-- Main Grid Content — always visible, cards handle offline inline -->
<div class="mx-auto flex w-full max-w-[1100px] flex-col gap-5">
  <!-- KPI Strip -->
  <KpiStrip />

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

    <NeuroBusPanel />
  </div>

  <!-- Runtime Diagnostics (collapsible, read-only) -->
  <RuntimePanel />

  <!-- Activity Timeline -->
  <ActivityPanel />

  <!-- Forge Tasks (live bridge only) -->
  {#if config.useLiveBridge}
    <ForgePanel />
  {/if}

  <!-- Live Log Panel -->
  <div
    class="flex h-60 shrink-0 flex-col gap-2 rounded-[20px] border border-hairline bg-bg-panel p-6"
  >
    <div class="flex items-center justify-between border-b border-hairline pb-2">
      <h2 class="font-sans text-xs font-semibold tracking-wider text-text-muted uppercase">
        Live System Logs
      </h2>
      <span class="font-mono text-[10px] text-text-muted">stream: /var/helios/aegis.log</span>
    </div>
    <div class="flex flex-1 scrollbar-thin flex-col gap-1 overflow-y-auto pr-2 font-mono text-xs">
      {#if $logs.length === 0}
        <div class="flex flex-1 items-center justify-center text-text-muted">no events yet</div>
      {:else}
        {#each $logs as log (log.id)}
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
      {/if}
    </div>
  </div>
</div>
