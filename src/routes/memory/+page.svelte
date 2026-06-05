<svelte:head>
  <title>AXIS - Memory</title>
</svelte:head>

<div
  class="flex h-full flex-col items-center justify-center gap-4 rounded-[20px] border border-hairline bg-bg-panel p-6 text-center"
>
  <div
    class="flex h-12 w-12 items-center justify-center rounded-full border border-hairline bg-accent-cyan/10 text-accent-cyan"
  >
    <svg
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      stroke-width="1.5"
      stroke="currentColor"
      class="h-6 w-6"
    >
      <path
        stroke-linecap="round"
        stroke-linejoin="round"
        d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0v3.75"
      />
    </svg>
  </div>
  <div>
    <h2 class="font-mono text-lg font-bold tracking-widest text-text-primary uppercase">
      Episodic Memory
    </h2>
    <p class="mt-2 max-w-sm text-xs text-text-muted">
      SQLite + MiniLM-384 semantic memory vectors consolidate on background loops.
    </p>
  </div>
</div>
