<script lang="ts">
  import { telemetry } from '$lib/stores/telemetry';
  import { scaleSparkline } from '$lib/utils/formatters';

  const keys = ['reward', 'novelty', 'attention', 'patience', 'threat', 'trust'] as const;

  const config = {
    reward: {
      label: 'Reward',
      textColor: 'text-accent-amber',
      borderColor: 'border-accent-amber/10 hover:border-accent-amber/30',
      bgColor: 'bg-accent-amber/[0.02] hover:bg-accent-amber/[0.05]',
      glowColor: '#F0B95C'
    },
    novelty: {
      label: 'Novelty',
      textColor: 'text-signal-blue',
      borderColor: 'border-signal-blue/10 hover:border-signal-blue/30',
      bgColor: 'bg-signal-blue/[0.02] hover:bg-signal-blue/[0.05]',
      glowColor: '#3B82F6'
    },
    attention: {
      label: 'Attention',
      textColor: 'text-text-primary',
      borderColor: 'border-hairline hover:border-text-primary/30',
      bgColor: 'bg-white/[0.01] hover:bg-white/[0.04]',
      glowColor: '#F0ECE3'
    },
    patience: {
      label: 'Patience',
      textColor: 'text-accent-violet',
      borderColor: 'border-accent-violet/10 hover:border-accent-violet/30',
      bgColor: 'bg-accent-violet/[0.02] hover:bg-accent-violet/[0.05]',
      glowColor: '#9B8CE0'
    },
    threat: {
      label: 'Threat',
      textColor: 'text-signal-red',
      borderColor: 'border-signal-red/10 hover:border-signal-red/30',
      bgColor: 'bg-signal-red/[0.02] hover:bg-signal-red/[0.05]',
      glowColor: '#E86A6A'
    },
    trust: {
      label: 'Trust',
      textColor: 'text-signal-green',
      borderColor: 'border-signal-green/10 hover:border-signal-green/30',
      bgColor: 'bg-signal-green/[0.02] hover:bg-signal-green/[0.05]',
      glowColor: '#4FC78A'
    }
  } as const;
</script>

<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
  {#each keys as key (key)}
    {@const item = config[key]}
    {@const history = $telemetry.neurobus[key]}
    {@const currentVal = history[history.length - 1]}
    {@const points = scaleSparkline(history, 80, 24)}
    {@const pointsString = points.map((p) => `${p.x},${p.y}`).join(' ')}

    <div
      class="flex items-center justify-between rounded-[16px] border p-4 backdrop-blur-sm transition-all duration-300 {item.borderColor} {item.bgColor}"
      style="min-height: 72px;"
    >
      <!-- Left: Label and Value -->
      <div class="flex flex-col gap-0.5">
        <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase">
          {item.label}
        </span>
        {#if $telemetry.connected}
          <span class="font-mono text-lg font-bold {item.textColor}">
            {currentVal.toFixed(2)}
          </span>
        {:else}
          <span class="flex items-center gap-1.5 font-mono text-lg font-bold text-signal-red">
            -- <span class="text-xs">⚠</span>
          </span>
        {/if}
      </div>

      <!-- Right: Sparkline (only when connected) -->
      <div class="flex h-6 items-center pr-2">
        {#if $telemetry.connected && pointsString}
          <svg class="h-6 w-20 overflow-visible" viewBox="0 0 80 24">
            <polyline
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              points={pointsString}
              style="filter: drop-shadow(0 0 3px {item.glowColor});"
              class="{item.textColor} transition-all duration-300"
            />
          </svg>
        {/if}
      </div>
    </div>
  {/each}
</div>
