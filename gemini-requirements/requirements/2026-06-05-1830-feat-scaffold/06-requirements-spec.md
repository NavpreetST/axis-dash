# Requirements Specification: Task 1 (feat/scaffold)

## 1. Problem Statement & Solution Overview
This requirement details the initial project setup, dependencies, configuration files, build pipeline, and developer mock-telemetry stores for **AXIS (Aegis eXecution Intelligence Surface)**, a SvelteKit web application designed as an operator control cockpit for the Aegis AI daemon.

The scaffold will lay the groundwork for SvelteKit, integrate Tailwind CSS v4.0, configure standard linting/formatting, set up the deploy pipeline via Vercel, and implement frontend-only stores simulating real-time telemetry inputs (uptime, tick rate, PAM, RPD, NeuroBus, live logs, chat) with a connection-drop simulator for offline states.

## 2. Functional Requirements
- **Framework & Routing**: SvelteKit (Svelte 5) initialized in minimal mode.
- **Mock Telemetry Data Store**:
  - A client-side simulated data source that publishes state updates at 1 Hz.
  - A simulated Server-Sent Event (SSE) log publisher that publishes log rows randomly every 3–8 seconds.
  - A chat simulator that replies to user messages with a delayed, simulated response.
  - A toggleable connection status switch to simulate offline states.
- **Aesthetic Guidelines**: Initial setup of the color token system using CSS custom properties (`@theme` in CSS) matching the exact handoff values:
  - App background (`bg/void`): `#16141E`
  - Panel surface (`bg/panel`): `#181B26` with ~75% opacity
  - Hairline borders (`hairline`): `#2A3145` with 40% opacity
  - Primary accent (`accent/cyan`): `#5FD0E0`
  - Secondary accent (`accent/violet`): `#9B8CE0`
  - Warning/Reward (`accent/amber`): `#F0B95C`
  - Primary text (`text/primary`): `#F0ECE3`
  - Muted labels (`text/muted`): `#938E9E`
  - Trust/Healthy (`signal/green`): `#4FC78A`
  - Threat/Error (`signal/red`): `#E86A6A`
  - Novelty (`signal/blue`): `#3B82F6`

## 3. Technical Requirements & File Paths
- **Vite Configuration (`vite.config.ts`)**: Integrate the `@tailwindcss/vite` plugin and SvelteKit.
- **Global Styling (`src/app.css`)**: Import Tailwind CSS (`@import "tailwindcss";`) and configure the theme tokens using the `@theme` directive.
- **Svelte Layout (`src/routes/+layout.svelte`)**: Import `src/app.css` and render Svelte children components.
- **Boilerplate Landing Page (`src/routes/+page.svelte`)**: Display a simple AXIS status summary wired to the mock stores showing simulated connection states.
- **Mock Stores (`src/lib/stores/`)**:
  - `telemetry.ts`: Readable store managing daemon stats (uptime, tick rate, PAM coherence, RPD quota, NeuroBus signals) with a toggleable connection variable.
  - `logs.ts`: Readable store streaming mock daemon logs periodically.
  - `chat.ts`: Writable store simulating the WebSocket chat session (agent replies simulated locally).

## 4. Linting & Formatting Rules
- **ESLint (`eslint.config.js`)**: Modern config for TypeScript/Svelte projects.
- **Prettier (`prettier.config.js` / `.prettierrc`)**: Enforce single quotes (`singleQuote: true`), semicolons (`semi: true`), and a 2-space indentation.

## 5. Acceptance Criteria
- [ ] Project successfully builds without errors (`npm run build`).
- [ ] Tailwind CSS v4.0 is fully integrated and successfully styles components.
- [ ] Prettier formatting and ESLint rules are applied cleanly without conflicts.
- [ ] The landing page successfully reads and displays real-time 1 Hz updates from the mock Svelte store.
- [ ] A simulated connection toggle exists on the landing page and successfully updates the connection state of the telemetry store.
- [ ] Vercel adapter config is added and ready for Hobby deployment.
