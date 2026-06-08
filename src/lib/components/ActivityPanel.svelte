<script lang="ts">
  import { logs, logsConnected } from '$lib/stores/logs';
  import { config } from '$lib/config';
  import { toActivityItems } from '$lib/utils/activityView';

  let bridgeStatus = $derived.by(() => {
    if (!config.useLiveBridge) return 'mock';
    return $logsConnected ? 'live-ok' : 'live-down';
  });

  let items = $derived(toActivityItems($logs));

  let showAll = $state(false);

  const MAX_VISIBLE = 8;
  let visible = $derived(showAll ? items : items.slice(0, MAX_VISIBLE));
</script>

<div class="flex flex-col gap-3 rounded-[20px] border border-hairline bg-bg-panel p-5">
  <div class="flex items-center justify-between border-b border-hairline pb-2">
    <h2 class="font-sans text-xs font-semibold tracking-wider text-text-muted uppercase">
      Activity
    </h2>
    {#if items.length > MAX_VISIBLE}
      <button
        type="button"
        onclick={() => (showAll = !showAll)}
        aria-expanded={showAll}
        class="font-mono text-[10px] text-accent-cyan transition hover:text-accent-cyan/80"
      >
        {showAll ? 'show less' : `+${items.length - MAX_VISIBLE} more`}
      </button>
    {/if}
  </div>

  <div class="flex max-h-48 scrollbar-thin flex-col gap-1 overflow-y-auto pr-1 font-mono text-xs">
    {#if bridgeStatus === 'live-down'}
      <div class="flex flex-1 items-center justify-center text-accent-amber">reconnecting…</div>
    {:else if items.length === 0}
      <div class="flex flex-1 items-center justify-center text-text-muted">no events yet</div>
    {:else}
      {#each visible as item (item.key)}
        <div class="flex gap-2 rounded p-0.5 leading-relaxed transition hover:bg-white/5">
          <span class="shrink-0 whitespace-nowrap text-text-muted">{item.time}</span>
          <span
            class="shrink-0 rounded-sm px-1 text-center text-[10px] font-bold uppercase
            {item.source === 'tick' ? 'bg-signal-blue/10 text-signal-blue' : ''}
            {item.source === 'mem' ? 'bg-accent-violet/10 text-accent-violet' : ''}
            {item.source === 'sys' ? 'bg-accent-cyan/10 text-accent-cyan' : ''}
            {item.source === 'task' ? 'bg-accent-amber/10 text-accent-amber' : ''}"
          >
            [{item.source}]
          </span>
          <span
            class="truncate
            {item.type === 'error' ? 'text-signal-red' : ''}
            {item.type === 'warning' ? 'text-accent-amber' : ''}
            {item.type === 'success' ? 'text-signal-green' : ''}
            {item.type === 'info' ? 'text-text-primary' : ''}"
          >
            {item.message}
          </span>
        </div>
      {/each}
    {/if}
  </div>
</div>
