<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { base } from '$app/paths';
  import { telemetry, chat, formatUptime, formatTickRate } from '$lib';
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

  // Route guard auth check
  onMount(() => {
    telemetry.start();

    const checkAuth = () => {
      const token = localStorage.getItem('HELIOS_TOKEN');
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
      telemetry.stop();
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
        <div class="flex items-center gap-3">
          <div
            class="h-2.5 w-2.5 animate-pulse rounded-full {$telemetry.connected
              ? 'bg-signal-green shadow-[0_0_8px_var(--color-signal-green)]'
              : 'bg-signal-red'}"
          ></div>
          <span class="text-sm font-bold tracking-widest text-text-primary uppercase">AXIS</span>
          <div
            class="hidden items-center gap-1.5 border-l border-hairline pl-3 font-mono text-[10px] text-text-muted md:flex"
          >
            <span
              >UPTIME: <strong class="text-accent-cyan"
                >{$telemetry.connected ? formatUptime($telemetry.uptime_seconds) : '--'}</strong
              ></span
            >
            <span class="text-hairline">•</span>
            <span
              >RATE: <strong class="text-text-primary"
                >{$telemetry.connected ? formatTickRate($telemetry.tick_rate) : '--'} tick/s</strong
              ></span
            >
          </div>
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

        <!-- Persistent mini Status metrics (Desktop View) -->
        <div class="hidden items-center gap-4 font-mono text-[10px] lg:flex">
          <!-- PAM coherence -->
          <div class="flex items-center gap-2">
            <span class="text-text-muted">PAM:</span>
            <span
              class="font-bold {$telemetry.pam >= 0.9
                ? 'text-signal-green'
                : $telemetry.pam >= 0.83
                  ? 'text-accent-amber'
                  : 'text-signal-red'}"
            >
              {$telemetry.pam}
            </span>
          </div>
          <!-- RPD -->
          <div class="flex items-center gap-2 border-l border-hairline pl-4">
            <span class="text-text-muted">RPD:</span>
            <span class="font-bold text-accent-amber"
              >{$telemetry.rpd_used} / {$telemetry.rpd_budget}</span
            >
          </div>
        </div>

        <!-- Mobile-only Telemetry Status Pill -->
        <div class="flex items-center gap-2 font-mono text-[9px] sm:hidden">
          {#if $telemetry.connected}
            <span
              class="rounded border border-signal-green/20 bg-signal-green/10 px-2 py-0.5 font-semibold text-signal-green uppercase"
            >
              {$telemetry.pam} PAM
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
          class="relative z-10 flex w-full shrink-0 flex-col overflow-hidden border-t border-hairline bg-bg-panel/10 sm:w-72 sm:border-t-0 sm:border-l
          {activeTab === 'chat' ? 'flex' : 'hidden lg:flex'}"
        >
          <!-- Chat Header -->
          <div
            class="flex h-12 shrink-0 items-center justify-between border-b border-hairline px-4 select-none"
          >
            <div class="flex items-center gap-2">
              <div class="h-2 w-2 animate-pulse rounded-full bg-accent-violet"></div>
              <span class="font-sans text-xs font-semibold tracking-wider text-text-muted uppercase"
                >Aegis Terminal</span
              >
            </div>
            <span class="font-mono text-[9px] text-accent-violet"
              >PAM COHERENCE: {$telemetry.pam}</span
            >
          </div>

          <!-- Chat messages viewport -->
          <div class="flex flex-1 scrollbar-thin flex-col gap-3 overflow-y-auto p-4">
            {#each $chat as msg (msg.id)}
              <div class="flex flex-col gap-1 {msg.sender === 'you' ? 'items-end' : 'items-start'}">
                <span class="font-mono text-[8px] text-text-muted"
                  >{msg.sender === 'you' ? 'YOU' : 'AEGIS'} • {msg.timestamp}</span
                >
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
          </div>

          <!-- Message Input area -->
          <div class="shrink-0 border-t border-hairline bg-bg-panel/25 p-3">
            <div
              class="flex items-center gap-2 rounded-xl border border-hairline bg-bg-void p-1 transition duration-200 focus-within:border-accent-cyan"
            >
              <input
                type="text"
                placeholder="Send command..."
                bind:value={chatInput}
                onkeypress={handleKeyPress}
                class="flex-1 border-0 bg-transparent px-2.5 py-1.5 font-mono text-xs text-text-primary outline-none placeholder:text-text-muted"
              />
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

<style>
  /* Custom scrollbar layout styling */
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
</style>
