<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { logs } from '$lib';
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
  <title>AXIS - Logs</title>
</svelte:head>

<div
  class="mx-auto flex h-full w-full max-w-[1100px] flex-col gap-4 rounded-[20px] border border-hairline bg-bg-panel p-6"
>
  <div class="flex items-center justify-between border-b border-hairline pb-3">
    <div>
      <h2 class="font-mono text-sm font-bold tracking-widest text-text-primary uppercase">
        Daemon Log Stream
      </h2>
      <p class="mt-1 font-sans text-[10px] text-text-muted">Full logs from /var/helios/aegis.log</p>
    </div>
  </div>

  <div class="flex flex-1 scrollbar-thin flex-col gap-1 overflow-y-auto pr-2 font-mono text-xs">
    {#if $logs.length === 0}
      <div class="flex flex-1 items-center justify-center text-text-muted">no events yet</div>
    {:else}
      {#each $logs as log (log.id)}
        <div class="flex gap-3 rounded p-1 leading-relaxed transition hover:bg-white/5">
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
