<script lang="ts">
  import { telemetry } from '$lib/stores/telemetry';
  import { scaleSparkline } from '$lib/utils/formatters';

  const keys = ['reward', 'novelty', 'attention', 'patience', 'threat', 'trust'] as const;

  const config = {
    reward: {
      label: 'Reward',
      textColor: 'text-accent-amber',
      borderColor: 'border-accent-amber/10 hover:border-accent-amber/30',
      bgColor: 'bg-accent-amber/[0.01] hover:bg-accent-amber/[0.03]',
      glowColor: '#F0B95C'
    },
    novelty: {
      label: 'Novelty',
      textColor: 'text-signal-blue',
      borderColor: 'border-signal-blue/10 hover:border-signal-blue/30',
      bgColor: 'bg-signal-blue/[0.01] hover:bg-signal-blue/[0.03]',
      glowColor: '#3B82F6'
    },
    attention: {
      label: 'Attention',
      textColor: 'text-text-primary',
      borderColor: 'border-hairline hover:border-text-primary/30',
      bgColor: 'bg-white/[0.01] hover:bg-white/[0.03]',
      glowColor: '#F0ECE3'
    },
    patience: {
      label: 'Patience',
      textColor: 'text-accent-violet',
      borderColor: 'border-accent-violet/10 hover:border-accent-violet/30',
      bgColor: 'bg-accent-violet/[0.01] hover:bg-accent-violet/[0.03]',
      glowColor: '#9B8CE0'
    },
    threat: {
      label: 'Threat',
      textColor: 'text-signal-red',
      borderColor: 'border-signal-red/10 hover:border-signal-red/30',
      bgColor: 'bg-signal-red/[0.01] hover:bg-signal-red/[0.03]',
      glowColor: '#E86A6A'
    },
    trust: {
      label: 'Trust',
      textColor: 'text-signal-green',
      borderColor: 'border-signal-green/10 hover:border-signal-green/30',
      bgColor: 'bg-signal-green/[0.01] hover:bg-signal-green/[0.03]',
      glowColor: '#4FC78A'
    }
  } as const;
</script>

<div class="grid w-full grid-cols-2 gap-3 md:grid-cols-3">
  {#each keys as key (key)}
    {@const item = config[key]}
    {@const currentVal = $telemetry.neurobus[key]}
    {@const history = $telemetry.neurobusHistory[key]}
    {@const points = scaleSparkline(history, 100, 36)}
    {@const pointsString = points.map((p) => `${p.x},${p.y}`).join(' ')}

    <div
      class="flex min-h-[96px] flex-col justify-between rounded-[20px] border p-4 backdrop-blur-sm transition-all duration-300 {item.borderColor} {item.bgColor}"
    >
      <!-- Top Section: Label and Current Value -->
      <div class="flex items-center justify-between">
        <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase">
          {item.label}
        </span>
        {#if $telemetry.connected}
          <span class="font-mono text-xs font-bold {item.textColor}">
            {currentVal.toFixed(2)}
          </span>
        {:else}
          <span class="font-mono text-xs font-bold text-text-muted"> -- </span>
        {/if}
      </div>

      <!-- Bottom Section: Sparkline -->
      <div class="mt-3 flex h-9 w-full items-end justify-center">
        {#if $telemetry.connected && pointsString}
          <svg
            class="h-full w-full overflow-visible"
            viewBox="0 0 100 36"
            preserveAspectRatio="none"
          >
            <polyline
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              points={pointsString}
              style="filter: drop-shadow(0 0 3px {item.glowColor}80);"
              class="{item.textColor} transition-all duration-300"
            />
          </svg>
        {:else}
          <!-- Offline/Disconnected flat dashed line -->
          <div class="h-[1px] w-full border-t border-dashed border-hairline/40"></div>
        {/if}
      </div>
    </div>
  {/each}
</div>
