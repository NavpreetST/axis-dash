<aside>
⚠️

**Living document** — update when decisions change. Last updated: 2026-06-05. Stack is locked. Visual spec is locked. Deferred items are listed at the bottom.

</aside>

## What you're building

**HELIOS Dashboard** (name TBD — rename options below) is a SvelteKit web app that renders a live cockpit for the **Aegis AI daemon** running on Helios1. It connects to a FastAPI mock backend via WebSocket and REST, displays real-time telemetry, surfaces the AI's internal signal state, and provides a chat interface to Aegis.

This is a **monitoring operator tool**, not a marketing page. Every element on screen maps to real live data. Nothing is decorative.

---

## Dashboard rename options

Pick one — update repo name, page titles, and the top bar once decided. Until then the codebase uses `helios-dash` and the UI header reads **HELIOS**.

| Acronym | Expansion | Vibe |
| --- | --- | --- |
| **AXIS** | Aegis eXecution Intelligence Surface | Clean, sharp, operational |
| **NOVA** | Neural Operations & Visibility Aggregator | Warm, expansive |
| **PULSE** | Process & Unit Live Signal Environment | Alive, heartbeat feel |
| **ORBIT** | Operational Runtime & Brain Intelligence Terminal | Spatial, cool |
| **NEXUS** | Neural EXecution & Understanding Surface | Connected, central |
| **VISTA** | Visual Intelligence & Status Telemetry Aggregator | Clear, panoramic |

---

## Stack (locked)

<aside>
🔒

Decisions locked 2026-06-05. Do not change framework, host, or repo type without explicit sign-off.

</aside>

| Layer | Choice | Notes |
| --- | --- | --- |
| Framework | **SvelteKit** (Vite + TypeScript, adapter-vercel) | No React. No Next.js. |
| Hosting | **Vercel** Hobby (deploy from GitHub) | Per-PR preview URLs automatic |
| Repo | **GitHub** public repo | Verify owner: NavpreetST |
| Styling | **Tailwind CSS** | Design tokens as CSS vars |
| Charts | **uPlot** (or Chart.js if simpler) | Lightweight, fast redraws |
| 3D Orb | **Three.js via Threlte** | Deferred — placeholder panel for now |
| Animation | **Motion** (ex-Framer Motion) + Svelte transitions + GSAP | Respect prefers-reduced-motion |
| Transport | Native WebSocket + SSE + fetch | No socket.io |
| Auth | Single bearer token (env var `HELIOS_TOKEN`) | Route guard on all pages except /login |
| Code review | **CodeRabbit** (free, public repos) + Aegis human gate | Install on repo before first PR |

---

## Visual spec

### Reference visual

<aside>
🎨

The **Lovable cockpit screenshot** is the target visual. Build to match it. Do not invent a new layout — implement the screenshot. Warm dark navy, glass cards, left icon nav rail, KPI row, signal-state hero panel, docked chat.

</aside>

### Colour tokens

| Token | Hex | Use |
| --- | --- | --- |
| `bg/void` | `#16141E` | App background (warm dark navy) |
| `bg/panel` | `#181B26` | Card surface — glass effect, ~75% opacity |
| `hairline` | `#2A3145` | 1px card borders, 40% opacity |
| `accent/cyan` | `#5FD0E0` | Primary accent, live glow, progress bars |
| `accent/violet` | `#9B8CE0` | Secondary accent, gradient pair with cyan |
| `accent/amber` | `#F0B95C` | Reward signal, warnings, RPD bar |
| `text/primary` | `#F0ECE3` | Body text — warm off-white |
| `text/muted` | `#938E9E` | Labels, panel titles, captions |
| `signal/green` | `#4FC78A` | Trust, healthy states |
| `signal/red` | `#E86A6A` | Threat, errors |
| `signal/blue` | `#3B82F6` | Novelty |

### Typography

- **Inter** — all UI labels, prose, chat bubbles, nav
- **JetBrains Mono** — all numbers, telemetry values, log lines, commit hashes
- KPI hero numbers: 30–32px. Panel titles: 12px uppercase letter-spaced muted. Body: 14px. Logs: 12px mono.

### Layout rules

- 1440px desktop-first. Left icon nav rail ~64px. Right-docked chat ~280px. Main content fluid between.
- **20px corner radius** on all cards. 24px internal padding. Soft diffuse shadows — no hard neon edges.
- Warm background with a faint amber radial glow in the top-right corner.
- Responsive: tablet → 3 tabs (Chat / Dashboard / Orb); mobile → chat-only with signal-state pill in header.

---

## Routes

| Route | Screen | v1 scope |
| --- | --- | --- |
| `/` | **Cockpit** | Full build — see panel inventory below |
| `/roadmap` | **Roadmap** | Placeholder page (data source TBD) |
| `/todo` | **Todo** | Placeholder page (data source TBD) |
| `/orb` | **Neural Orb** | Placeholder — full-bleed dark + "orb offline" text |
| `/memory` | **Memory** | Placeholder page |
| `/logs` | **Logs** | Full log stream with filters (reuse Live Log component) |
| `/drift` | **Drift** | Placeholder page |
| `/commits` | **Commits** | Placeholder page |
| `/login` | **Login** | Bearer token entry — no route guard here |

SvelteKit client-side routing. Each route = its own `+page.svelte`. All routes except `/login` require a valid token in localStorage.

---

## Data contracts

All endpoints served by the **FastAPI mock backend** (already scaffolded).

| Endpoint | Type | Notes |
| --- | --- | --- |
| `WS /state` | WebSocket | 1 Hz state snapshot — uptime, tick, PAM, RPD, neurobus, hidden_state |
| `WS /chat` | WebSocket | Chat send/receive |
| `SSE /logs` | Server-Sent Events | Streaming log line objects |
| `GET /api/commits` | REST | Recent commit list |
| `GET /api/roadmap` | REST | Roadmap items (source TBD) |
| `GET /api/todo` | REST | Todo items |
| `GET /api/memory` | REST | Memory summary |
| `GET /api/diagnostic` | REST | System diagnostic |
| `GET /api/drift` | REST | Drift report (claims vs reality) |

Auth: `Authorization: Bearer <token>` on all requests. Token stored in localStorage after login.

### `/state` WebSocket payload fields

| Field | Type | Notes |
| --- | --- | --- |
| `uptime_seconds` | number | Format as `14h 22m` in UI |
| `tick_rate` | float | Rolling 60s average |
| `pam` | float 0–1 | Green ≥ 0.90 / amber 0.83–0.89 / red < 0.83 |
| `rpd_used` | int | Gemini calls used today |
| `rpd_budget` | int | Always 240 at Phase 0 |
| `provider` | string | Active renderer: `gemini-2.5-flash`, `groq`, or `template` |
| `neurobus.reward` | float 0–1 | Gold bar |
| `neurobus.novelty` | float 0–1 | Blue bar |
| `neurobus.attention` | float 0–1 | Off-white bar |
| `neurobus.patience` | float 0–1 | Violet bar |
| `neurobus.threat` | float 0–1 | Red bar |
| `neurobus.trust` | float 0–1 | Green bar |
| `hidden_state` | float[][] | 8×8 matrix for heatmap (later phase) |
| `connected` | bool | False = show daemon-offline state |

---

## Panel inventory — Cockpit v1

| Panel | Data | Key UI elements |
| --- | --- | --- |
| **KPI — Uptime** | `uptime_seconds` | Big mono number formatted `14h 22m`, subtitle "since last restart" |
| **KPI — Tick rate** | `tick_rate` | Big number + "tick/s", subtitle "rolling 60s avg" |
| **KPI — PAM** | `pam` | Big number + thin gradient progress bar, colour changes by threshold |
| **KPI — RPD** | `rpd_used / rpd_budget` | Fraction `37 / 240`  • thin amber progress bar |
| **Signal State** (hero) | `neurobus.*` | 6 horizontal gauge bars, colour-coded, label left, value right |
| **System** | `provider`, `rpd_used` | Provider rows with status pill (ok / standby / error) + RPD usage bar |
| **Live Log** | `SSE /logs` | Streaming mono lines — timestamp + `[source]` tag + colour by type + filter dropdown |
| **Aegis Chat** | `WS /chat` | Bubble list (Aegis vs You), thin coloured affect border, 📎 memory chip, prompt chips, mic + send input |

---

## Phase 0 ground truths

<aside>
⚠️

**Never inflate these.** These are real values as of 2026-06-05. The dashboard must display what is actually true.

</aside>

- NCP brain: **41,361 parameters** — hidden_dim 64, input_dim 388, output_dim 40, **random-init (untrained at Phase 0)**
- Renderer chain: `gemini-2.5-flash → groq → template` — Gemini does ~100% of work right now
- Memory: SQLite + MiniLM-384 — T1 working / T2 episodic / T3 identity-locked
- NeuroBus: exactly **6 scalars** — reward, novelty, attention, patience, threat, trust
- PAM: a **separate coherence metric** — not a NeuroBus scalar. Red threshold < 0.83.
- RPD budget: **240 Gemini calls/day**, resets America/Los_Angeles timezone
- Launch method: `nohup` (not systemd) — this is a known drift point
- Socket: `/run/aegis/aegis.sock` — persistent REPL connection
- One-shot `echo | aegis` is **broken** (finding F8)

---

## Project management

### How tasks flow

```
Aegis drafts task brief
  → NavpreetS approves & posts to Antigravity
    → Antigravity builds on a feature branch
      → PR opened on GitHub
        → CodeRabbit auto-reviews
          → Aegis reviews diff in Notion thread
            → NavpreetS merges
              → Vercel auto-deploys preview URL
                → Confirm on preview → promote to main
```

### Branching strategy

- `main` — protected, always deployable, auto-deploys to production
- `feat/<scope>` — one branch per feature task (e.g. `feat/kpi-cards`)
- `fix/<scope>` — bug fixes
- `chore/<scope>` — tooling, config, deps

One task = one branch = one PR. Keep PRs small and focused.

### Review rules

- **CodeRabbit** runs automatically on every PR (free on public repos — install before first PR)
- **Aegis** reviews the diff in the Notion thread and flags issues before NavpreetS merges
- **NavpreetS** is the final merge gate — no auto-merge ever
- PRs must have a passing Vercel preview deploy before review starts

### Suggested first sprint (Tasks 1–9)

| # | Branch | Scope |
| --- | --- | --- |
| 1 | `feat/scaffold` | SvelteKit project, Tailwind, adapter-vercel, folder structure, mock WS server |
| 2 | `feat/layout-shell` | App shell: left nav rail, top bar, route layout, design token CSS vars, theme |
| 3 | `feat/kpi-cards` | 4 KPI cards wired to `/state` WS — uptime, tick, PAM, RPD |
| 4 | `feat/signal-state` | Signal State hero panel — 6 gauge bars wired to `neurobus.*` |
| 5 | `feat/system-panel` | System card — provider rows, status pills, RPD bar |
| 6 | `feat/live-log` | SSE log stream, colour-coded by type, filter dropdown |
| 7 | `feat/chat` | Aegis chat panel — WS, bubbles, affect borders, prompt chips, input |
| 8 | `feat/login` | Login page + bearer token route guard |
| 9 | `feat/placeholder-routes` | Skeleton pages for /roadmap /todo /memory /drift /commits /orb |

### Vercel setup steps

1. Create public GitHub repo (confirm owner first)
2. Connect repo to Vercel (Hobby — free, no card)
3. Set env var `HELIOS_TOKEN` in Vercel project settings
4. Every PR auto-generates a preview URL
5. Merge to `main` → production URL

---

## Handoff checklist

- [ ]  Pick a dashboard name from the acronym list and update repo + UI
- [ ]  Confirm GitHub repo owner (NavpreetST vs NavpreetD) and create `<name>-dash` public repo
- [ ]  Share the Lovable cockpit screenshot with Antigravity as the visual target
- [ ]  Connect GitHub repo to Vercel (Hobby)
- [ ]  Install CodeRabbit on the repo
- [ ]  Give Antigravity Task 1 (scaffold only — not the whole app)
- [ ]  Verify FastAPI mock backend is accessible for Antigravity to test against

---

## Deferred — do not build yet

| Item | When |
| --- | --- |
| 3D Neural Orb (Three.js / Threlte) | When orb is live and trained |
| `/roadmap` and `/todo` live data | After Notion DB is set up |
| `/drift` live comparison | After diagnostic endpoint is wired |
| Custom domain (`.dev` via Name.com) | When site is live and stable |
| Dedicated server / systemd | Post Phase 0 |
| Light mode | Probably never — confirm |
| Hidden State 8×8 heatmap | Later phase — omit from v1 |