<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { base } from '$app/paths';
  import { telemetry, chat } from '$lib';
  import { config } from '$lib/config';
  import { getToken } from '$lib/api/client';
  import { startBridge, stopBridge, type BridgeClients } from '$lib/api/bridge';
  import { coalesceConsecutive, isPinnedToBottom } from '$lib/utils/chatView';
  import './layout.css';

  // Import Lucide Icons
  import {
    LayoutDashboard,
    Compass,
    ListTodo,
    Radio,
    Database,
    Terminal,
    GitCompare,
    GitCommit,
    LogOut,
    Send
  } from '@lucide/svelte';

  let { children } = $props();

  // Responsive state for tablet tabs
  let activeTab = $state('dashboard'); // 'dashboard' | 'chat' | 'orb'
  let chatInput = $state('');

  // --- Chat viewport: auto-scroll + jump-to-latest ---
  let chatScrollEl: HTMLDivElement | undefined = $state();
  // True when the user is at (or within ~40px of) the bottom of the
  // chat viewport. Initialised to `true` so a fresh mount scrolls to
  // the latest seed message instead of leaving the user stranded at
  // the top of an overflowed panel.
  let isPinned = $state(true);
  let showJumpButton = $state(false);

  // Display-only coalesced view of the chat log. The underlying store
  // still records every event — coalesce is a UI affordance so a
  // daemon error flood (e.g. the bridge repeating
  // {"error":"socket_unavailable",...} while the daemon is down) does
  // not bury the user under hundreds of identical rows.
  const displayMessages = $derived(coalesceConsecutive($chat));

  // Auto-scroll to the bottom when a new message arrives, but only
  // if the user is currently pinned. `requestAnimationFrame` defers
  // the scroll to after Svelte's DOM patch so the layout is final
  // when `scrollHeight` is read.
  $effect(() => {
    // Touch the underlying store length so this effect re-runs on
    // every new message. (`displayMessages.length` would skip the
    // re-run when a coalesced "same text, increment count" event
    // arrives, which is the exact case we need to keep pinned.)
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    $chat.length;
    if (!isPinned) return;
    requestAnimationFrame(() => {
      if (chatScrollEl) {
        chatScrollEl.scrollTop = chatScrollEl.scrollHeight;
      }
    });
  });

  function onChatScroll() {
    if (!chatScrollEl) return;
    isPinned = isPinnedToBottom(
      chatScrollEl.scrollTop,
      chatScrollEl.clientHeight,
      chatScrollEl.scrollHeight
    );
    showJumpButton = !isPinned;
  }

  function jumpToLatest() {
    if (!chatScrollEl) return;
    chatScrollEl.scrollTop = chatScrollEl.scrollHeight;
    isPinned = true;
    showJumpButton = false;
  }

  // Bridge status for the header heartbeat dot.
  // 'mock'      → green : mock mode (default; intentional, not an error)
  // 'live-ok'   → green : live mode on, /state socket is open
  // 'misconfig' → amber : live mode on, but token or URLs are missing
  // 'live-down' → red   : live mode on, but disconnected (startup or error)
  let hasToken = $state(false);
  let hasUrls = $state(false);
  let bridgeStatus = $derived.by(() => {
    if (!config.useLiveBridge) return 'mock' as const;
    if (!hasUrls || !hasToken) return 'misconfig' as const;
    return $telemetry.connected ? ('live-ok' as const) : ('live-down' as const);
  });
  let bridgeStatusLabel = $derived.by(() => {
    switch (bridgeStatus) {
      case 'mock':
        return 'Mock mode — PUBLIC_USE_LIVE_BRIDGE is not set to a truthy value (true/1/yes/on/enabled)';
      case 'misconfig':
        if (!hasUrls && !hasToken)
          return 'Set PUBLIC_HELIOS_API_URL, PUBLIC_HELIOS_WS_URL, and PUBLIC_HELIOS_TOKEN (or log in)';
        if (!hasToken) return 'No token — set PUBLIC_HELIOS_TOKEN or log in';
        return 'PUBLIC_HELIOS_API_URL or PUBLIC_HELIOS_WS_URL is missing';
      case 'live-ok':
        return 'live data flowing from the Helios bridge';
      case 'live-down':
        return 'Live mode on — reconnecting… (socket dropped; backed off and retrying)';
    }
  });

  // Route guard auth check
  onMount(() => {
    let bridge: BridgeClients | null = null;

    // `hasUrls` must reflect whether the operator actually set the URL
    // env vars — `config.heliosApiUrl` always has a loopback default, so
    // a truthiness check on the resolved values would never see the
    // misconfig state. `config.hasExplicitUrls` is true only when both
    // PUBLIC_HELIOS_API_URL and PUBLIC_HELIOS_WS_URL are non-empty.
    hasUrls = config.hasExplicitUrls;
    hasToken = Boolean(getToken());

    if (config.useLiveBridge) {
      bridge = startBridge();
      chat.setLiveSender((text) => bridge!.chat.send(text));
    } else {
      telemetry.start();
    }

    const checkAuth = () => {
      // `getToken()` falls back to the build-time `PUBLIC_HELIOS_TOKEN`
      // env var when localStorage is empty. Reading localStorage
      // directly would force-redirect any deployment that relies on the
      // env-var token to `/login`, where the user has nothing to type.
      const token = getToken();
      if (!token && $page.url.pathname !== base + '/login') {
        goto(base + '/login');
      }
    };

    checkAuth();

    const unsubscribePage = page.subscribe(() => {
      checkAuth();
      // Reset active tab to dashboard when changing route so child content is visible
      if ($page.url.pathname === base + '/orb') {
        activeTab = 'orb';
      } else {
        activeTab = 'dashboard';
      }
    });

    return () => {
      if (bridge) {
        chat.setLiveSender(null);
        stopBridge(bridge);
      } else {
        telemetry.stop();
      }
      unsubscribePage();
    };
  });

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

  function handleLogout() {
    localStorage.removeItem('HELIOS_TOKEN');
    goto(base + '/login');
  }

  // Nav rail config
  const navItems = [
    { path: '/', label: 'Cockpit', icon: LayoutDashboard },
    { path: '/roadmap', label: 'Roadmap', icon: Compass },
    { path: '/todo', label: 'Tasks', icon: ListTodo },
    { path: '/orb', label: 'Neural Orb', icon: Radio },
    { path: '/memory', label: 'Memory', icon: Database },
    { path: '/logs', label: 'Logs', icon: Terminal },
    { path: '/drift', label: 'Drift', icon: GitCompare },
    { path: '/commits', label: 'Commits', icon: GitCommit }
  ];
</script>

<svelte:head>
  <link rel="icon" href="/favicon.svg" />
</svelte:head>

{#if $page.url.pathname === base + '/login'}
  <!-- Simple render for login screen without outer shell layouts -->
  {@render children()}
{:else}
  <div
    class="flex h-screen w-screen overflow-hidden bg-bg-void font-sans text-text-primary select-none"
  >
    <!-- LEFT NAV RAIL (Hidden on mobile, 64px width on tablet+) -->
    <aside
      class="z-20 hidden w-16 shrink-0 flex-col items-center justify-between border-r border-hairline bg-bg-panel/50 py-6 sm:flex"
    >
      <div class="flex w-full flex-col items-center gap-6">
        <!-- Main AXIS logo icon -->
        <div
          class="flex h-10 w-10 items-center justify-center rounded-xl border border-accent-cyan/35 bg-accent-cyan/15 text-sm font-bold tracking-widest text-accent-cyan shadow-sm shadow-accent-cyan/10"
        >
          A
        </div>

        <!-- Navigation Links -->
        <nav class="flex w-full flex-col gap-3 px-2">
          {#each navItems as item (item.path)}
            {@const Icon = item.icon}
            {@const isActive =
              $page.url.pathname === (item.path === '/' ? base || '/' : base + item.path)}
            <a
              href={base + item.path}
              class="group relative flex h-12 w-12 cursor-pointer items-center justify-center rounded-xl transition-all duration-200
                {isActive
                ? 'border border-accent-cyan/30 bg-accent-cyan/10 text-accent-cyan shadow-md shadow-accent-cyan/5'
                : 'border border-transparent text-text-muted hover:bg-white/5 hover:text-text-primary'}"
            >
              <Icon class="h-5 w-5 transition-transform duration-200 group-hover:scale-105" />

              <!-- Tooltip on hover -->
              <span
                class="invisible absolute left-16 z-30 rounded-lg border border-hairline bg-bg-panel px-2.5 py-1 font-mono text-[10px] whitespace-nowrap text-text-primary opacity-0 shadow-lg transition-all duration-200 group-hover:visible group-hover:opacity-100"
              >
                {item.label}
              </span>
            </a>
          {/each}
        </nav>
      </div>

      <!-- Logout option at rail bottom -->
      <button
        onclick={handleLogout}
        class="group relative flex h-12 w-12 cursor-pointer items-center justify-center rounded-xl text-text-muted transition-all duration-200 hover:bg-signal-red/10 hover:text-signal-red"
      >
        <LogOut class="h-5 w-5" />
        <span
          class="invisible absolute left-16 z-30 rounded-lg border border-hairline bg-bg-panel px-2.5 py-1 font-mono text-[10px] whitespace-nowrap text-signal-red opacity-0 shadow-lg transition-all duration-200 group-hover:visible group-hover:opacity-100"
        >
          Disconnect
        </span>
      </button>
    </aside>

    <!-- MAIN INTERFACE CONTAINER -->
    <div class="relative flex min-w-0 flex-1 flex-col overflow-hidden">
      <!-- PERSISTENT TOP HEADER BAR -->
      <header
        class="z-10 flex h-16 shrink-0 items-center justify-between border-b border-hairline bg-bg-panel/20 px-6 select-none"
      >
        <!-- Brand Title & Global Heartbeat -->
        <div class="group flex items-center gap-3">
          <div
            class="h-2.5 w-2.5 animate-pulse rounded-full {bridgeStatus === 'live-ok' ||
            bridgeStatus === 'mock'
              ? 'bg-signal-green shadow-[0_0_8px_var(--color-signal-green)]'
              : bridgeStatus === 'misconfig'
                ? 'bg-accent-amber shadow-[0_0_8px_var(--color-accent-amber)]'
                : 'bg-signal-red shadow-[0_0_8px_var(--color-signal-red)]'}"
            title={bridgeStatusLabel}
          ></div>
          <span class="text-sm font-bold tracking-widest text-text-primary uppercase">AXIS</span>
          <span
            class="invisible ml-1 max-w-[260px] rounded-md border border-hairline bg-bg-panel px-2 py-0.5 font-mono text-[9px] whitespace-nowrap text-text-muted opacity-0 shadow-sm transition-all duration-200 group-hover:visible group-hover:opacity-100"
          >
            {bridgeStatusLabel}
          </span>
        </div>

        <!-- Tablet / Mobile Tab switch controls -->
        <div
          class="flex items-center rounded-xl border border-hairline bg-bg-void/50 p-0.5 font-mono text-[10px] lg:hidden"
        >
          <button
            onclick={() => (activeTab = 'dashboard')}
            class="cursor-pointer rounded-lg px-3 py-1.5 transition-all duration-200 {activeTab ===
            'dashboard'
              ? 'bg-accent-cyan/15 font-bold text-accent-cyan'
              : 'text-text-muted hover:text-text-primary'}"
          >
            PANELS
          </button>
          <button
            onclick={() => (activeTab = 'chat')}
            class="cursor-pointer rounded-lg px-3 py-1.5 transition-all duration-200 {activeTab ===
            'chat'
              ? 'bg-accent-cyan/15 font-bold text-accent-cyan'
              : 'text-text-muted hover:text-text-primary'}"
          >
            AEGIS
          </button>
          <button
            onclick={() => (activeTab = 'orb')}
            class="cursor-pointer rounded-lg px-3 py-1.5 transition-all duration-200 {activeTab ===
            'orb'
              ? 'bg-accent-cyan/15 font-bold text-accent-cyan'
              : 'text-text-muted hover:text-text-primary'}"
          >
            ORB
          </button>
        </div>

        <!-- Mobile-only Telemetry Status Pill -->
        <div class="flex items-center gap-2 font-mono text-[9px] sm:hidden">
          {#if $telemetry.connected}
            <span
              class="rounded border border-signal-green/20 bg-signal-green/10 px-2 py-0.5 font-semibold text-signal-green uppercase"
            >
              ONLINE
            </span>
          {:else}
            <span
              class="rounded border border-signal-red/20 bg-signal-red/10 px-2 py-0.5 font-semibold text-signal-red uppercase"
            >
              OFFLINE
            </span>
          {/if}
        </div>
      </header>

      <!-- WRAPPER FOR ROUTE CHILD CONTENT & PERSISTENT CHAT -->
      <div class="relative flex min-h-0 flex-1">
        <!-- FLUID PAGE MAIN CONTENT VIEW -->
        <main
          class="min-w-0 flex-1 scrollbar-thin overflow-y-auto p-6 md:p-8
          {activeTab === 'dashboard' || activeTab === 'orb' ? 'flex' : 'hidden sm:flex'}"
        >
          {#if activeTab === 'orb'}
            <div
              class="flex flex-1 flex-col items-center justify-center rounded-[20px] border border-hairline bg-[#0d0c11] p-12 text-center"
            >
              <div
                class="mb-6 flex h-20 w-20 animate-spin items-center justify-center rounded-full border border-dashed border-text-muted/30"
              >
                <div
                  class="h-12 w-12 animate-ping rounded-full border border-dotted border-text-muted/40"
                ></div>
              </div>
              <h2 class="font-mono text-lg font-bold tracking-widest text-text-muted uppercase">
                Orb Offline
              </h2>
              <p class="mt-2 max-w-sm font-sans text-xs text-text-muted">
                3D Neural Orb is deferred until the cognitive field daemon is fully trained.
              </p>
            </div>
          {:else}
            <div class="min-w-0 flex-1">
              {@render children()}
            </div>
          {/if}
        </main>

        <!-- DOCKED AEGIS CHAT PANEL (Hidden on tablet/mobile unless toggled active) -->
        <aside
          class="flex shrink-0 flex-col overflow-hidden border-t border-hairline bg-bg-panel/10 transition-all duration-300 ease-out
            max-sm:fixed max-sm:inset-0 max-sm:z-50
            {activeTab === 'chat' ? 'max-sm:translate-y-0' : 'max-sm:translate-y-full'}
            sm:relative sm:inset-auto sm:z-10 sm:w-72 sm:translate-y-0 sm:border-t-0 sm:border-l
            {activeTab === 'chat' ? 'flex' : 'hidden lg:flex'}"
        >
          <!-- Chat Header -->
          <div
            class="flex h-12 shrink-0 items-center justify-between border-b border-hairline px-4 select-none"
          >
            <div class="flex items-center gap-2">
              <!-- Mobile close button -->
              <button
                onclick={() => (activeTab = 'dashboard')}
                class="flex cursor-pointer items-center justify-center rounded-lg p-1 text-text-muted transition hover:bg-white/5 hover:text-text-primary sm:hidden"
                aria-label="Close chat"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="2"
                  stroke="currentColor"
                  class="h-4 w-4"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="m4.5 15.75 7.5-7.5 7.5 7.5"
                  />
                </svg>
              </button>
              <div class="h-2 w-2 animate-pulse rounded-full bg-accent-violet"></div>
              <span class="font-sans text-xs font-semibold tracking-wider text-text-muted uppercase"
                >Aegis Terminal</span
              >
            </div>
            <span class="font-mono text-[9px] text-accent-violet"
              >PAM COHERENCE: {$telemetry.connected && $telemetry.pam !== null
                ? $telemetry.pam
                : '--'}</span
            >
          </div>

          <!-- Chat messages viewport -->
          <div
            bind:this={chatScrollEl}
            onscroll={onChatScroll}
            class="relative flex flex-1 scrollbar-thin flex-col gap-3 overflow-y-auto p-4"
          >
            {#each displayMessages as msg (msg.key)}
              <div class="flex flex-col gap-1 {msg.sender === 'you' ? 'items-end' : 'items-start'}">
                <span class="font-mono text-[8px] text-text-muted">
                  {msg.sender === 'you' ? 'YOU' : 'AEGIS'} • {msg.timestamp}
                  {#if msg.count > 1}
                    <span
                      class="ml-1 rounded bg-bg-void/60 px-1 py-px text-accent-violet"
                      title="{msg.count} identical consecutive messages"
                      aria-label="{msg.count} identical consecutive messages"
                      data-testid="coalesce-counter">×{msg.count}</span
                    >
                  {/if}
                </span>
                <div
                  class="max-w-[85%] rounded-2xl border px-3.5 py-2 text-xs leading-relaxed
                  {msg.sender === 'you'
                    ? 'rounded-tr-none border-accent-amber/30 bg-accent-amber/10 text-text-primary'
                    : 'rounded-tl-none border-hairline bg-bg-void/80 text-text-primary'}"
                >
                  {msg.text}
                </div>
              </div>
            {/each}

            <!-- Jump to latest: only visible when the user has
                 scrolled up. Sticky-positioned to float above the
                 messages without taking layout space, and hidden once
                 the user clicks it (or scrolls back to the bottom). -->
            {#if showJumpButton}
              <button
                type="button"
                onclick={jumpToLatest}
                data-testid="jump-to-latest"
                aria-label="Jump to latest message"
                class="sticky bottom-2 z-20 mx-auto cursor-pointer rounded-full border border-accent-cyan/30 bg-bg-panel/95 px-3 py-1 font-mono text-[10px] font-semibold text-accent-cyan shadow-md shadow-accent-cyan/10 backdrop-blur transition-all hover:bg-accent-cyan/15"
              >
                Jump to latest ↓
              </button>
            {/if}
          </div>

          <!-- Message Input area -->
          <div class="shrink-0 border-t border-hairline bg-bg-panel/25 p-2">
            <div
              class="flex items-center gap-1.5 rounded-xl border bg-bg-void p-1 transition duration-200 {chatInput.trim()
                ? 'border-accent-cyan/60'
                : 'border-hairline'} focus-within:border-accent-cyan"
            >
              <input
                type="text"
                placeholder="Send command..."
                bind:value={chatInput}
                onkeypress={handleKeyPress}
                class="flex-1 border-0 bg-transparent px-2.5 py-1.5 font-mono text-xs text-text-primary outline-none placeholder:text-text-muted"
              />
              {#if chatInput.trim()}
                <div class="h-1.5 w-1.5 rounded-full bg-signal-green" title="ready"></div>
              {/if}
              <button
                onclick={handleSendChat}
                disabled={!chatInput.trim()}
                class="cursor-pointer rounded-lg bg-accent-cyan p-1.5 text-bg-void transition hover:bg-accent-cyan/80 disabled:cursor-not-allowed disabled:opacity-30"
              >
                <Send class="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </aside>
      </div>
    </div>
  </div>
{/if}
