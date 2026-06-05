<script lang="ts">
  import { AlertTriangle } from '@lucide/svelte';

  // ── Props (Svelte 5 runes) ─────────────────────────────────────
  interface Props {
    label: string;
    value: string;
    unit?: string;
    subtitle?: string;
    connected?: boolean;
    barPercent?: number;
    barColorClass?: string;
    barGlowClass?: string;
    valueColorClass?: string;
  }

  let {
    label,
    value,
    unit = '',
    subtitle = '',
    connected = true,
    barPercent = undefined,
    barColorClass = 'bg-accent-amber',
    barGlowClass = '',
    valueColorClass = 'text-text-primary'
  }: Props = $props();
</script>

<div class="kpi-card flex flex-col gap-1 rounded-[20px] border border-hairline bg-bg-panel p-5">
  <!-- Label (always visible) -->
  <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase">{label}</span>

  {#if connected}
    <!-- Big mono number -->
    <span class="font-mono text-xl font-bold {valueColorClass}">
      {value}
      {#if unit}
        <span class="text-xs text-text-muted">{unit}</span>
      {/if}
    </span>

    <!-- Optional subtitle -->
    {#if subtitle}
      <span class="font-sans text-[10px] text-text-muted">{subtitle}</span>
    {/if}

    <!-- Optional progress bar -->
    {#if barPercent !== undefined}
      <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-hairline">
        <div
          class="h-full rounded-full transition-all duration-300 {barColorClass} {barGlowClass}"
          style="width: {barPercent}%"
        ></div>
      </div>
    {/if}
  {:else}
    <!-- Offline fail-safe: inline -- + warning icon -->
    <span class="flex items-center gap-2 font-mono text-xl font-bold text-text-muted">
      --
      <AlertTriangle size={14} class="text-accent-amber" />
    </span>
    <span class="font-sans text-[10px] text-accent-amber">daemon offline</span>
  {/if}
</div>
