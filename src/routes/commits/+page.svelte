<svelte:head>
  <title>AXIS - Commits</title>
</svelte:head>

<div
  class="mx-auto flex h-full w-full max-w-[1100px] flex-col items-center justify-center gap-4 rounded-[20px] border border-hairline bg-bg-panel p-6 text-center"
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
        d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5"
      />
    </svg>
  </div>
  <div>
    <h2 class="font-mono text-lg font-bold tracking-widest text-text-primary uppercase">
      Daemon Commits
    </h2>
    <p class="mt-2 max-w-sm text-xs text-text-muted">
      Recent commit logs of the Aegis daemon repository will sync here once connected to the API
      endpoint.
    </p>
  </div>
</div>
