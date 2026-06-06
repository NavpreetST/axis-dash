<script lang="ts">
  import { telemetry } from '$lib/stores/telemetry';
  import {
    formatUptime,
    formatTickRate,
    pamThreshold,
    rpdPercent,
    rpdOverBudget
  } from '$lib/utils/formatters';
  import { AlertTriangle } from '@lucide/svelte';

  // PAM color mapping
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

  let uptimeDisplay = $derived(formatUptime($telemetry.uptime_seconds));
  let tickDisplay = $derived(formatTickRate($telemetry.tick_rate));
  let pamBucket = $derived(pamThreshold($telemetry.pam));
  let rpdPct = $derived(rpdPercent($telemetry.rpd_used, $telemetry.rpd_budget));
  let rpdOver = $derived(rpdOverBudget($telemetry.rpd_used, $telemetry.rpd_budget));
</script>

<div
  class="kpi-strip flex h-14 w-full shrink-0 items-center overflow-hidden rounded-[20px] border border-hairline bg-bg-panel backdrop-blur-md"
>
  <!-- Uptime -->
  <div class="flex h-full flex-1 items-center justify-between border-r border-hairline/30 px-5">
    <div class="flex flex-col justify-center">
      <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase">Uptime</span>
      {#if $telemetry.connected}
        <span class="font-mono text-sm font-bold text-accent-cyan">{uptimeDisplay}</span>
      {:else}
        <span class="flex items-center gap-1.5 font-mono text-sm font-bold text-text-muted">
          -- <AlertTriangle size={12} class="text-accent-amber" />
        </span>
      {/if}
    </div>
  </div>

  <!-- Tick Rate -->
  <div class="flex h-full flex-1 items-center justify-between border-r border-hairline/30 px-5">
    <div class="flex flex-col justify-center">
      <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase">Tick Rate</span>
      {#if $telemetry.connected}
        <span class="font-mono text-sm font-bold text-text-primary">
          {tickDisplay} <span class="text-[10px] font-normal text-text-muted">tick/s</span>
        </span>
      {:else}
        <span class="flex items-center gap-1.5 font-mono text-sm font-bold text-text-muted">
          -- <AlertTriangle size={12} class="text-accent-amber" />
        </span>
      {/if}
    </div>
  </div>

  <!-- PAM Coherence -->
  <div class="flex h-full flex-1 items-center justify-between border-r border-hairline/30 px-5">
    <div class="flex flex-col justify-center">
      <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase"
        >PAM Coherence</span
      >
      {#if $telemetry.connected}
        <span class="font-mono text-sm font-bold {pamColorMap[pamBucket]}">
          {$telemetry.pam.toFixed(2)}
        </span>
      {:else}
        <span class="flex items-center gap-1.5 font-mono text-sm font-bold text-text-muted">
          -- <AlertTriangle size={12} class="text-accent-amber" />
        </span>
      {/if}
    </div>
    {#if $telemetry.connected}
      <div class="h-1 w-9 shrink-0 overflow-hidden rounded-full bg-hairline/30">
        <div
          class="h-full rounded-full transition-all duration-300 {pamBarMap[pamBucket]} {pamGlowMap[
            pamBucket
          ]}"
          style="width: {$telemetry.pam * 100}%"
        ></div>
      </div>
    {/if}
  </div>

  <!-- RPD Usage -->
  <div class="flex h-full flex-1 items-center justify-between px-5">
    <div class="flex flex-col justify-center">
      <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase">RPD Usage</span>
      {#if $telemetry.connected}
        <span
          class="font-mono text-sm font-bold {rpdOver ? 'text-signal-red' : 'text-accent-amber'}"
        >
          {$telemetry.rpd_used} / {$telemetry.rpd_budget}
        </span>
      {:else}
        <span class="flex items-center gap-1.5 font-mono text-sm font-bold text-text-muted">
          -- <AlertTriangle size={12} class="text-accent-amber" />
        </span>
      {/if}
    </div>
    {#if $telemetry.connected}
      <div class="h-1 w-9 shrink-0 overflow-hidden rounded-full bg-hairline/30">
        <div
          class="h-full rounded-full transition-all duration-300 {rpdOver
            ? 'bg-signal-red'
            : 'bg-accent-amber'} {rpdOver ? 'bar-glow-red' : 'bar-glow-amber'}"
          style="width: {rpdPct}%"
        ></div>
      </div>
    {/if}
  </div>
</div>
