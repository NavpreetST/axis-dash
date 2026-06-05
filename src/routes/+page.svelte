<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import {
    telemetry,
    logs,
    formatUptime,
    formatTickRate,
    pamThreshold,
    rpdPercent,
    rpdOverBudget
  } from '$lib';
  import KpiCard from '$lib/components/KpiCard.svelte';

  // Start the store loops on mount
  onMount(() => {
    telemetry.start();
    logs.start();
  });

  onDestroy(() => {
    telemetry.stop();
    logs.stop();
  });

  // ── Reactive derived values for KPI cards ────────────────────
  let uptimeDisplay = $derived(formatUptime($telemetry.uptime_seconds));
  let tickDisplay = $derived(formatTickRate($telemetry.tick_rate));
  let pamBucket = $derived(pamThreshold($telemetry.pam));
  let rpdPct = $derived(rpdPercent($telemetry.rpd_used, $telemetry.rpd_budget));
  let rpdOver = $derived(rpdOverBudget($telemetry.rpd_used, $telemetry.rpd_budget));

  // PAM colour mapping
  const pamColorMap = {
    green: 'text-signal-green',
    amber: 'text-accent-amber',
    red: 'text-signal-red'
  } as const;
  const pamBarMap = {
    green: 'bg-signal-green',
    amber: 'bg-accent-amber',
    red: 'bg-signal-red'
  } as const;
  const pamGlowMap = {
    green: 'bar-glow-green',
    amber: 'bar-glow-amber',
    red: 'bar-glow-red'
  } as const;
</script>

<svelte:head>
  <title>AXIS - Cockpit</title>
</svelte:head>

<!-- Main Grid Content — always visible, cards handle offline inline -->
<div class="flex h-full flex-col gap-6">
  <!-- KPI Cards Row -->
  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
    <!-- Uptime -->
    <KpiCard
      label="Uptime"
      value={uptimeDisplay}
      subtitle="since last restart"
      valueColorClass="text-accent-cyan"
      connected={$telemetry.connected}
    />

    <!-- Tick Rate -->
    <KpiCard
      label="Tick Rate"
      value={tickDisplay}
      unit="tick/s"
      subtitle="rolling 60s avg"
      connected={$telemetry.connected}
    />

    <!-- PAM Coherence -->
    <KpiCard
      label="PAM Coherence"
      value={String($telemetry.pam)}
      valueColorClass={pamColorMap[pamBucket]}
      barPercent={$telemetry.pam * 100}
      barColorClass={pamBarMap[pamBucket]}
      barGlowClass={pamGlowMap[pamBucket]}
      connected={$telemetry.connected}
    />

    <!-- RPD Usage -->
    <KpiCard
      label="RPD Usage"
      value="{$telemetry.rpd_used} / {$telemetry.rpd_budget}"
      valueColorClass={rpdOver ? 'text-signal-red' : 'text-accent-amber'}
      barPercent={rpdPct}
      barColorClass={rpdOver ? 'bg-signal-red' : 'bg-accent-amber'}
      barGlowClass={rpdOver ? 'bar-glow-red' : 'bar-glow-amber'}
      connected={$telemetry.connected}
    />
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
    </div>
  </div>
</div>

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
