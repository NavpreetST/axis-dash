<script lang="ts">
  import { telemetry } from '$lib/stores/telemetry';
  import { AlertTriangle } from '@lucide/svelte';

  const keys = ['reward', 'novelty', 'attention', 'patience', 'threat', 'trust'] as const;

  const config = {
    reward: {
      label: 'Reward',
      textColor: 'text-accent-amber',
      barColor: 'bg-accent-amber',
      glowColor: '#F0B95C'
    },
    novelty: {
      label: 'Novelty',
      textColor: 'text-signal-blue',
      barColor: 'bg-signal-blue',
      glowColor: '#3B82F6'
    },
    attention: {
      label: 'Attention',
      textColor: 'text-text-primary',
      barColor: 'bg-text-primary',
      glowColor: '#F0ECE3'
    },
    patience: {
      label: 'Patience',
      textColor: 'text-accent-violet',
      barColor: 'bg-accent-violet',
      glowColor: '#9B8CE0'
    },
    threat: {
      label: 'Threat',
      textColor: 'text-signal-red',
      barColor: 'bg-signal-red',
      glowColor: '#E86A6A'
    },
    trust: {
      label: 'Trust',
      textColor: 'text-signal-green',
      barColor: 'bg-signal-green',
      glowColor: '#4FC78A'
    }
  } as const;
</script>

<div class="flex flex-col gap-1.5">
  {#each keys as key (key)}
    {@const item = config[key]}
    {@const val = $telemetry.neurobus[key]}

    <div
      class="flex h-8 items-center justify-between rounded-lg border border-transparent px-3 transition-all duration-200 hover:border-hairline/20 hover:bg-white/[0.02]"
    >
      <!-- Left: Label -->
      <span
        class="w-24 shrink-0 font-sans text-[10px] font-medium tracking-wider text-text-muted uppercase"
      >
        {item.label}
      </span>

      <!-- Middle: Tiny progress bar (if connected) -->
      {#if $telemetry.connected}
        <div class="mx-4 h-1.5 flex-1 overflow-hidden rounded-full bg-hairline/10">
          <div
            class="h-full rounded-full transition-all duration-300 {item.barColor}"
            style="width: {val * 100}%; box-shadow: 0 0 6px {item.glowColor}66;"
          ></div>
        </div>
      {:else}
        <!-- Disconnected filler -->
        <div class="mx-4 h-[1px] flex-1 bg-hairline/10"></div>
      {/if}

      <!-- Right: Value -->
      <div class="w-12 text-right">
        {#if $telemetry.connected}
          <span class="font-mono text-xs font-bold {item.textColor}">
            {val.toFixed(2)}
          </span>
        {:else}
          <span
            class="flex items-center justify-end gap-1 font-mono text-xs font-bold text-text-muted"
          >
            -- <AlertTriangle size={10} class="text-accent-amber" />
          </span>
        {/if}
      </div>
    </div>
  {/each}
</div>
