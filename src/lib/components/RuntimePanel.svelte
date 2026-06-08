<script lang="ts">
  import { telemetry } from '$lib/stores/telemetry';
  import { ChevronDown } from '@lucide/svelte';
  import { formatRuntimeValue } from '$lib/utils/formatters';

  let expanded = $state(false);

  function toggle() {
    expanded = !expanded;
  }

  const fields = [
    { key: 'commit' as const, label: 'Commit' },
    { key: 'socket_path' as const, label: 'Socket' },
    { key: 'launch_method' as const, label: 'Launch' },
    { key: 'renderer_chain' as const, label: 'Renderer' },
    { key: 'memory_backend' as const, label: 'Memory' },
    { key: 'ncp' as const, label: 'NCP' },
    { key: 'budget' as const, label: 'Budget' },
    { key: 'known_issues' as const, label: 'Issues' }
  ];
</script>

<div class="overflow-hidden rounded-[20px] border border-hairline bg-bg-panel">
  <button
    type="button"
    onclick={toggle}
    aria-expanded={expanded}
    class="flex w-full cursor-pointer items-center justify-between px-5 py-3 transition-colors hover:bg-white/[0.02]"
  >
    <span class="font-sans text-[10px] font-semibold tracking-wider text-text-muted uppercase"
      >Runtime Diagnostics</span
    >
    <div class="flex items-center gap-2">
      {#if $telemetry.runtime}
        <span class="font-mono text-[9px] text-accent-cyan">
          {$telemetry.runtime.commit?.slice(0, 7) ?? '--'}
        </span>
      {/if}
      <ChevronDown
        class="h-3.5 w-3.5 text-text-muted transition-transform duration-200 {expanded
          ? 'rotate-180'
          : ''}"
      />
    </div>
  </button>

  {#if expanded}
    <div class="border-t border-hairline px-5 py-3">
      {#if $telemetry.runtime}
        {@const rt = $telemetry.runtime}
        <div class="grid grid-cols-2 gap-x-6 gap-y-1.5 md:grid-cols-4">
          {#each fields as field (field.key)}
            <div class="flex flex-col">
              <span class="font-sans text-[9px] tracking-wider text-text-muted uppercase">
                {field.label}
              </span>
              {#if field.key === 'known_issues'}
                <span class="font-mono text-[11px] text-text-primary">
                  {#if rt.known_issues && rt.known_issues.length > 0}
                    {rt.known_issues.join('; ')}
                  {:else}
                    --
                  {/if}
                </span>
              {:else}
                <span class="font-mono text-[11px] text-text-primary">
                  {formatRuntimeValue(rt[field.key])}
                </span>
              {/if}
            </div>
          {/each}
        </div>
      {:else}
        <p class="font-mono text-[10px] text-text-muted">--</p>
      {/if}
    </div>
  {/if}
</div>
