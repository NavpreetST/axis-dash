<script lang="ts">
  import { createMockOrbState } from '$lib/orb/mockState';

  const orbState = createMockOrbState();
</script>

<svelte:head>
  <title>AXIS - Helios Orb — Phase 0</title>
</svelte:head>

<div class="mx-auto flex h-full w-full max-w-[1100px] flex-col gap-5">
  <div class="flex flex-col gap-4 rounded-[20px] border border-hairline bg-bg-panel p-6">
    <div class="flex items-center justify-between border-b border-hairline pb-2">
      <h2 class="font-mono text-lg font-bold tracking-widest text-text-primary uppercase">
        Helios Orb — Phase 0
      </h2>
      <span class="font-mono text-[10px] text-accent-cyan">stub</span>
    </div>

    <p class="font-mono text-xs text-text-muted">
      State contract scaffolding. No visual renderer yet — see
      <code class="text-accent-cyan">src/lib/orb/</code> for types and mock data.
    </p>
  </div>

  <div class="flex flex-col gap-3 rounded-[20px] border border-hairline bg-bg-panel p-6">
    <div class="border-b border-hairline pb-2">
      <h3 class="font-mono text-xs font-semibold tracking-wider text-text-muted uppercase">
        Debug: Raw Orb State
      </h3>
    </div>
    <pre
      class="max-h-[600px] scrollbar-thin overflow-y-auto rounded-lg bg-bg-void p-4 font-mono text-[10px] leading-relaxed text-text-primary">{JSON.stringify(
        orbState,
        null,
        2
      )}</pre>
  </div>
</div>
