<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { telemetry, logs, chat } from '$lib';

  let chatInput = $state('');

  // Start the store loops on mount
  onMount(() => {
    telemetry.start();
    logs.start();
  });

  onDestroy(() => {
    telemetry.stop();
    logs.stop();
  });

  // Helper to format uptime seconds into h, m, s
  function formatUptime(seconds: number): string {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h}h ${m}m ${s}s`;
  }

  function handleSendChat() {
    if (!chatInput.trim()) return;
    chat.sendMessage(chatInput.trim());
    chatInput = '';
  }

  function handleKeyPress(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      handleSendChat();
    }
  }
</script>

<svelte:head>
  <title>AXIS Cockpit</title>
</svelte:head>

<main class="flex min-h-screen flex-col gap-6 bg-bg-void p-8 font-sans text-text-primary">
  <!-- Top bar -->
  <header class="flex items-center justify-between border-b border-hairline pb-4">
    <div class="flex items-center gap-3">
      <div class="h-3 w-3 animate-pulse rounded-full bg-accent-cyan"></div>
      <h1 class="font-sans text-xl font-bold tracking-wider text-accent-cyan uppercase">AXIS</h1>
      <span class="font-mono text-xs text-text-muted">Aegis eXecution Intelligence Surface</span>
    </div>

    <div class="flex items-center gap-4">
      <div class="flex items-center gap-2 font-mono text-sm">
        <span class="text-text-muted">Status:</span>
        {#if $telemetry.connected}
          <span
            class="rounded border border-signal-green/20 bg-signal-green/10 px-2 py-0.5 text-signal-green"
            >ONLINE</span
          >
        {:else}
          <span
            class="text-shadow-glow rounded border border-signal-red/20 bg-signal-red/10 px-2 py-0.5 text-signal-red"
            >OFFLINE</span
          >
        {/if}
      </div>
      <button
        onclick={telemetry.toggleConnection}
        class="cursor-pointer rounded-lg border px-4 py-1.5 font-mono text-xs font-medium transition-all duration-200 {$telemetry.connected
          ? 'border-signal-red text-signal-red hover:bg-signal-red/10'
          : 'border-signal-green text-signal-green hover:bg-signal-green/10'}"
      >
        {$telemetry.connected ? 'SIMULATE DISCONNECT' : 'RECONNECT DAEMON'}
      </button>
    </div>
  </header>

  {#if !$telemetry.connected}
    <div
      class="flex flex-1 flex-col items-center justify-center rounded-[20px] border border-hairline bg-bg-panel p-12 transition-all"
    >
      <div
        class="mb-4 h-16 w-16 animate-spin rounded-full border-2 border-dashed border-signal-red"
      ></div>
      <h2 class="font-mono text-lg font-bold tracking-widest text-signal-red uppercase">
        Aegis Daemon Offline
      </h2>
      <p class="mt-2 max-w-md text-center font-sans text-sm text-text-muted">
        Connection to the AI execution surface has been severed. Reconnect the daemon to restore
        real-time telemetry pipelines.
      </p>
    </div>
  {:else}
    <!-- Content Grid -->
    <div class="grid flex-1 grid-cols-1 gap-6 lg:grid-cols-3">
      <!-- Left Column: KPIs & Signals -->
      <div class="flex flex-col gap-6 lg:col-span-2">
        <!-- KPI Cards Row -->
        <div class="grid grid-cols-1 gap-4 md:grid-cols-4">
          <div class="flex flex-col gap-1 rounded-[20px] border border-hairline bg-bg-panel p-5">
            <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase"
              >Uptime</span
            >
            <span class="font-mono text-xl font-bold text-accent-cyan"
              >{formatUptime($telemetry.uptime_seconds)}</span
            >
            <span class="font-sans text-[10px] text-text-muted">since last restart</span>
          </div>

          <div class="flex flex-col gap-1 rounded-[20px] border border-hairline bg-bg-panel p-5">
            <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase"
              >Tick Rate</span
            >
            <span class="font-mono text-xl font-bold text-text-primary"
              >{$telemetry.tick_rate} <span class="text-xs text-text-muted">tick/s</span></span
            >
            <span class="font-sans text-[10px] text-text-muted">rolling 60s avg</span>
          </div>

          <div class="flex flex-col gap-1 rounded-[20px] border border-hairline bg-bg-panel p-5">
            <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase"
              >PAM Coherence</span
            >
            <span
              class="font-mono text-xl font-bold {$telemetry.pam >= 0.9
                ? 'text-signal-green'
                : $telemetry.pam >= 0.83
                  ? 'text-accent-amber'
                  : 'text-signal-red'}">{$telemetry.pam}</span
            >
            <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-hairline">
              <div
                class="h-full rounded-full transition-all duration-300 {$telemetry.pam >= 0.9
                  ? 'bg-signal-green'
                  : $telemetry.pam >= 0.83
                    ? 'bg-accent-amber'
                    : 'bg-signal-red'}"
                style="width: {$telemetry.pam * 100}%"
              ></div>
            </div>
          </div>

          <div class="flex flex-col gap-1 rounded-[20px] border border-hairline bg-bg-panel p-5">
            <span class="font-sans text-[10px] tracking-wider text-text-muted uppercase"
              >RPD Usage</span
            >
            <span class="font-mono text-xl font-bold text-accent-amber"
              >{$telemetry.rpd_used}
              <span class="text-xs text-text-muted">/ {$telemetry.rpd_budget}</span></span
            >
            <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-hairline">
              <div
                class="h-full rounded-full bg-accent-amber"
                style="width: {($telemetry.rpd_used / $telemetry.rpd_budget) * 100}%"
              ></div>
            </div>
          </div>
        </div>

        <!-- Signal State (Hero Panel) -->
        <div
          class="flex flex-1 flex-col gap-4 rounded-[20px] border border-hairline bg-bg-panel p-6"
        >
          <div class="flex items-center justify-between border-b border-hairline pb-2">
            <h2 class="font-sans text-xs font-semibold tracking-wider text-text-muted uppercase">
              NeuroBus Signal State
            </h2>
            <span class="font-mono text-[10px] text-accent-cyan"
              >Active Renderer: {$telemetry.provider}</span
            >
          </div>

          <div class="grid flex-1 grid-cols-1 justify-center gap-6 md:grid-cols-2">
            {#each Object.entries($telemetry.neurobus) as [key, val] (key)}
              <div class="flex flex-col gap-2">
                <div class="flex justify-between font-mono text-xs">
                  <span class="text-text-muted capitalize">{key}</span>
                  <span class="text-text-primary">{val}</span>
                </div>
                <div class="h-2.5 w-full overflow-hidden rounded-full bg-hairline">
                  <div
                    class="h-full rounded-full transition-all duration-500
                      {key === 'reward' ? 'bg-accent-amber' : ''}
                      {key === 'novelty' ? 'bg-signal-blue' : ''}
                      {key === 'attention' ? 'bg-text-primary' : ''}
                      {key === 'patience' ? 'bg-accent-violet' : ''}
                      {key === 'threat' ? 'bg-signal-red' : ''}
                      {key === 'trust' ? 'bg-signal-green' : ''}
                    "
                    style="width: {val * 100}%"
                  ></div>
                </div>
              </div>
            {/each}
          </div>
        </div>

        <!-- Live Log Panel -->
        <div class="flex h-60 flex-col gap-2 rounded-[20px] border border-hairline bg-bg-panel p-6">
          <div class="flex items-center justify-between border-b border-hairline pb-2">
            <h2 class="font-sans text-xs font-semibold tracking-wider text-text-muted uppercase">
              Live System Logs
            </h2>
            <span class="font-mono text-[10px] text-text-muted">stream: /var/helios/aegis.log</span>
          </div>
          <div
            class="flex flex-1 scrollbar-thin flex-col gap-1 overflow-y-auto pr-2 font-mono text-xs"
          >
            {#each $logs as log (log.timestamp + '-' + log.message)}
              <div class="flex gap-3 rounded p-0.5 leading-relaxed transition hover:bg-white/5">
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
          </div>
        </div>
      </div>

      <!-- Right Column: Docked Aegis Chat -->
      <div
        class="flex h-full min-h-[500px] flex-col gap-4 rounded-[20px] border border-hairline bg-bg-panel p-6"
      >
        <div class="flex items-center justify-between border-b border-hairline pb-3">
          <div class="flex items-center gap-2">
            <div class="h-2 w-2 rounded-full bg-accent-violet"></div>
            <h2 class="font-sans text-xs font-semibold tracking-wider text-text-muted uppercase">
              Aegis Terminal
            </h2>
          </div>
          <span class="font-mono text-[10px] text-accent-violet">Coherence: {$telemetry.pam}</span>
        </div>

        <!-- Messages stream -->
        <div class="flex flex-1 scrollbar-thin flex-col gap-3 overflow-y-auto pr-2">
          {#each $chat as msg (msg.timestamp + '-' + msg.text)}
            <div class="flex flex-col gap-1 {msg.sender === 'you' ? 'items-end' : 'items-start'}">
              <div class="font-mono text-[9px] text-text-muted">
                {msg.sender === 'you' ? 'YOU' : 'AEGIS'} • {msg.timestamp}
              </div>
              <div
                class="max-w-[85%] rounded-2xl border px-4 py-2 text-xs leading-relaxed
                {msg.sender === 'you'
                  ? 'rounded-tr-none border-accent-amber/30 bg-accent-amber/10 text-text-primary'
                  : 'rounded-tl-none border-hairline bg-bg-void text-text-primary'}
              "
              >
                {msg.text}
              </div>
            </div>
          {/each}
        </div>

        <!-- Message Input -->
        <div
          class="flex items-center gap-2 rounded-xl border border-hairline bg-bg-void p-1 transition duration-200 focus-within:border-accent-cyan"
        >
          <input
            type="text"
            placeholder="Send command to Aegis..."
            bind:value={chatInput}
            onkeypress={handleKeyPress}
            class="flex-1 border-0 bg-transparent px-3 py-2 font-mono text-xs text-text-primary outline-none placeholder:text-text-muted"
          />
          <button
            onclick={handleSendChat}
            disabled={!chatInput.trim()}
            class="cursor-pointer rounded-lg bg-accent-cyan p-2 text-bg-void transition hover:bg-accent-cyan/80 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <!-- Send Arrow SVG -->
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="currentColor"
              class="h-4 w-4"
            >
              <path
                d="M3.478 2.404a.75.75 0 0 0-.926.941l2.432 7.905H13.5a.75.75 0 0 1 0 1.5H4.984l-2.432 7.905a.75.75 0 0 0 .926.94 60.519 60.519 0 0 0 18.445-8.986.75.75 0 0 0 0-1.218A60.517 60.517 0 0 0 3.478 2.404Z"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
  {/if}
</main>

<style>
  /* Scrollbar styles */
  .scrollbar-thin::-webkit-scrollbar {
    width: 4px;
    height: 4px;
  }
  .scrollbar-thin::-webkit-scrollbar-track {
    background: transparent;
  }
  .scrollbar-thin::-webkit-scrollbar-thumb {
    background: var(--color-hairline);
    border-radius: 4px;
  }
  .scrollbar-thin::-webkit-scrollbar-thumb:hover {
    background: var(--color-text-muted);
  }
</style>
