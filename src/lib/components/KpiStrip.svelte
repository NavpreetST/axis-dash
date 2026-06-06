<script lang="ts">
  import { telemetry } from '$lib/stores/telemetry';
  import { formatUptime, formatTickRate, pamThreshold, rpdPercent } from '$lib/utils/formatters';

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
  let pamBucket = $derived($telemetry.pam !== null ? pamThreshold($telemetry.pam) : 'amber');
  let rpdPct = $derived(rpdPercent($telemetry.rpd_used, $telemetry.rpd_budget));

  // RPD near or over budget logic: >= 85% of budget
  let rpdIsWarningOrOver = $derived($telemetry.rpd_used >= $telemetry.rpd_budget * 0.85);
</script>

<div class="grid w-full shrink-0 grid-cols-2 gap-4 lg:grid-cols-4">
  <!-- Uptime Card -->
  <div
    class="kpi-card flex min-h-[112px] flex-col justify-between rounded-[20px] border border-hairline bg-bg-panel p-5"
  >
    <span class="font-sans text-[10px] font-semibold tracking-wider text-text-muted uppercase"
      >Uptime</span
    >
    <div class="my-1.5 flex items-baseline">
      {#if $telemetry.connected}
        <span class="font-mono text-[30px] leading-none font-bold tracking-tight text-accent-cyan"
          >{uptimeDisplay}</span
        >
      {:else}
        <span
          class="flex items-center gap-1.5 font-mono text-[30px] leading-none font-bold text-text-muted"
        >
          -- <span class="text-lg text-accent-amber">⚠</span>
        </span>
      {/if}
    </div>
    <span class="font-sans text-[10px] leading-none text-text-muted">since last restart</span>
  </div>

  <!-- Tick Rate Card -->
  <div
    class="kpi-card flex min-h-[112px] flex-col justify-between rounded-[20px] border border-hairline bg-bg-panel p-5"
  >
    <span class="font-sans text-[10px] font-semibold tracking-wider text-text-muted uppercase"
      >Tick Rate</span
    >
    <div class="my-1.5 flex items-baseline gap-1">
      {#if $telemetry.connected}
        <span class="font-mono text-[30px] leading-none font-bold tracking-tight text-text-primary"
          >{tickDisplay}</span
        >
        <span class="font-sans text-[11px] text-text-muted">tick/s</span>
      {:else}
        <span
          class="flex items-center gap-1.5 font-mono text-[30px] leading-none font-bold text-text-muted"
        >
          -- <span class="text-lg text-accent-amber">⚠</span>
        </span>
      {/if}
    </div>
    <span class="font-sans text-[10px] leading-none text-text-muted">rolling 60s avg</span>
  </div>

  <!-- PAM Coherence Card -->
  <div
    class="kpi-card flex min-h-[112px] flex-col justify-between rounded-[20px] border border-hairline bg-bg-panel p-5"
  >
    <div class="flex items-center justify-between">
      <span class="font-sans text-[10px] font-semibold tracking-wider text-text-muted uppercase"
        >PAM Coherence</span
      >
    </div>
    <div class="my-1.5 flex items-baseline">
      {#if $telemetry.connected && $telemetry.pam !== null}
        <span
          class="font-mono text-[30px] font-bold tracking-tight {pamColorMap[
            pamBucket
          ]} leading-none"
        >
          {$telemetry.pam.toFixed(2)}
        </span>
      {:else}
        <span
          class="flex items-center gap-1.5 font-mono text-[30px] leading-none font-bold text-text-muted"
        >
          -- <span class="text-lg text-accent-amber">⚠</span>
        </span>
      {/if}
    </div>
    <div class="h-1.5 w-full overflow-hidden rounded-full bg-hairline/25">
      {#if $telemetry.connected && $telemetry.pam !== null}
        <div
          class="h-full rounded-full transition-all duration-300 {pamBarMap[pamBucket]} {pamGlowMap[
            pamBucket
          ]}"
          style="width: {$telemetry.pam * 100}%"
        ></div>
      {/if}
    </div>
  </div>

  <!-- RPD Usage Card -->
  <div
    class="kpi-card flex min-h-[112px] flex-col justify-between rounded-[20px] border border-hairline bg-bg-panel p-5"
  >
    <div class="flex items-center justify-between">
      <span class="font-sans text-[10px] font-semibold tracking-wider text-text-muted uppercase"
        >RPD Usage</span
      >
    </div>
    <div class="my-1.5 flex items-baseline">
      {#if $telemetry.connected}
        <span
          class="font-mono text-[30px] font-bold tracking-tight {rpdIsWarningOrOver
            ? 'text-signal-red'
            : 'text-accent-amber'} leading-none"
        >
          {$telemetry.rpd_used}
          <span class="text-sm font-normal text-text-muted">/ {$telemetry.rpd_budget}</span>
        </span>
      {:else}
        <span
          class="flex items-center gap-1.5 font-mono text-[30px] leading-none font-bold text-text-muted"
        >
          -- <span class="text-lg text-accent-amber">⚠</span>
        </span>
      {/if}
    </div>
    <div class="h-1.5 w-full overflow-hidden rounded-full bg-hairline/25">
      {#if $telemetry.connected}
        <div
          class="h-full rounded-full transition-all duration-300 {rpdIsWarningOrOver
            ? 'bar-glow-red bg-signal-red'
            : 'bar-glow-amber bg-accent-amber'}"
          style="width: {rpdPct}%"
        ></div>
      {/if}
    </div>
  </div>
</div>
