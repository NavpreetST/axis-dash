# Technical Context & Findings

## Architecture & Tech Stack

- **Framework**: SvelteKit (Svelte 5)
- **Language**: TypeScript (Strict Mode)
- **Styling**: Tailwind CSS v4.0 (CSS-first, Vite-native plugin, no `tailwind.config.js`)
- **Adapter**: `adapter-vercel` (for automated Hobby Vercel deployments from GitHub)
- **Linter & Formatter**: ESLint + Prettier

## Proposed Directory Structure (to be created by scaffold)

```
/
├── .svelte-kit/
├── gemini-requirements/         # Requirements documentation
├── src/
│   ├── app.css                  # Main global styles (Tailwind imports and @theme configuration)
│   ├── app.html                 # Main HTML shell
│   ├── lib/
│   │   └── stores/
│   │       ├── telemetry.ts     # Frontend simulation of WebSocket state snapshot (1 Hz)
│   │       ├── logs.ts          # Frontend simulation of Server-Sent Events (SSE) log stream
│   │       └── chat.ts          # Frontend simulation of WebSocket-based Aegis Chat
│   ├── routes/
│   │   ├── +layout.svelte       # Main layout (imports app.css)
│   │   └── +page.svelte         # Landing page / entrypoint
│   └── index.css                # (Created/Modified as the base design system token definition)
├── static/                      # Static assets
├── eslint.config.js             # Linter config
├── prettier.config.js           # Formatter config
├── tsconfig.json                # TypeScript config
├── vite.config.ts               # Vite configuration (with @tailwindcss/vite plugin)
├── package.json                 # Dependency list
└── vercel.json                  # Optional Vercel deployment configuration
```

## Mock Telemetry Store Implementation (Task 1 Scope)

To simulate the backend WS and SSE streams client-side, we will implement:

1. **`telemetry.ts`**:
   - Updates every 1000ms (1 Hz) to simulate the FastAPI `/state` payload.
   - Emits mock parameters:
     - `uptime_seconds` (incrementing counter)
     - `tick_rate` (slight variations around `9.8`)
     - `pam` (slight variations around `0.91`, ensuring it changes threshold colours correctly)
     - `rpd_used` (starting at 37)
     - `rpd_budget` (always 240)
     - `connected` (always true for mock)
     - `neurobus` scalars (reward, novelty, attention, patience, threat, trust)
2. **`logs.ts`**:
   - Emits a new structured log item every 3–8 seconds mimicking the SSE `/logs` payload.
   - Includes fields like `timestamp`, `source`, `type`, and `message`.
3. **`chat.ts`**:
   - Stores conversation list (You and Aegis).
   - Generates simulated delayed agent replies when a new user message is submitted to mimic the `/chat` WebSocket.

## External Integration & Deployment

- Automated deployments via Vercel GitHub integration.
- Since we are in `C:\Users\Navdeep\Desktop\Code\helios-dash`, we will initialize the project directly here.
