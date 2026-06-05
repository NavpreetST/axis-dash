<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { base } from '$app/paths';

  let token = $state('');
  let errorMessage = $state('');

  onMount(() => {
    // If token already exists, redirect to cockpit
    if (localStorage.getItem('HELIOS_TOKEN')) {
      goto(base + '/');
    }
  });

  function handleLogin(e: SubmitEvent) {
    e.preventDefault();
    if (!token.trim()) {
      errorMessage = 'Token cannot be empty';
      return;
    }

    // Save to localStorage
    localStorage.setItem('HELIOS_TOKEN', token.trim());
    goto(base + '/');
  }
</script>

<svelte:head>
  <title>AXIS - Login</title>
</svelte:head>

<main
  class="flex min-h-screen items-center justify-center bg-bg-void p-4 font-sans text-text-primary"
>
  <div
    class="flex w-full max-w-md flex-col gap-6 rounded-[20px] border border-hairline bg-bg-panel p-8 shadow-lg"
  >
    <div class="flex flex-col gap-2 text-center">
      <h1 class="text-2xl font-bold tracking-widest text-accent-cyan uppercase">AXIS</h1>
      <p class="font-mono text-xs tracking-wider text-text-muted uppercase">
        Aegis eXecution Intelligence Surface
      </p>
    </div>

    <form onsubmit={handleLogin} class="flex flex-col gap-4">
      <div class="flex flex-col gap-2">
        <label for="token-input" class="font-mono text-xs tracking-wider text-text-muted uppercase"
          >Bearer Security Token</label
        >
        <input
          id="token-input"
          type="password"
          placeholder="Enter HELIOS_TOKEN..."
          bind:value={token}
          class="w-full rounded-xl border border-hairline bg-bg-void px-4 py-3 font-mono text-sm text-text-primary transition duration-200 outline-none placeholder:text-text-muted focus:border-accent-cyan"
        />
        {#if errorMessage}
          <span class="font-mono text-xs text-signal-red">{errorMessage}</span>
        {/if}
      </div>

      <button
        type="submit"
        class="w-full cursor-pointer rounded-xl bg-accent-cyan py-3 font-mono text-sm font-bold text-bg-void shadow-md shadow-accent-cyan/10 transition duration-200 hover:bg-accent-cyan/90"
      >
        CONNECT TO SURFACE
      </button>
    </form>

    <div class="text-center font-mono text-[10px] text-text-muted">
      Session token stored locally for authenticated access.
    </div>
  </div>
</main>
