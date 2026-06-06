<svelte:head>
  <title>AXIS - Tasks</title>
</svelte:head>

<div
  class="mx-auto flex h-full w-full max-w-[1100px] flex-col items-center justify-center gap-4 rounded-[20px] border border-hairline bg-bg-panel p-6 text-center"
>
  <div
    class="flex h-12 w-12 items-center justify-center rounded-full border border-hairline bg-accent-amber/10 text-accent-amber"
  >
    <!-- ListIcon SVG placeholder -->
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
        d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 0 0 2.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 0 0-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75 2.25 2.25 0 0 0-.1-.664m-5.8 0A2.251 2.251 0 0 1 13.5 2.25H15c1.03 0 1.9.732 2.076 1.704m-7.404 9.77a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Zm0 3a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Zm0 3a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM9 7.5h7.5"
      />
    </svg>
  </div>
  <div>
    <h2 class="font-mono text-lg font-bold tracking-widest text-text-primary uppercase">
      Todo Tasks
    </h2>
    <p class="mt-2 max-w-sm text-xs text-text-muted">
      Tasks synchronization is offline. Ensure database integrations are configured in Notion
      workspace.
    </p>
  </div>
</div>
