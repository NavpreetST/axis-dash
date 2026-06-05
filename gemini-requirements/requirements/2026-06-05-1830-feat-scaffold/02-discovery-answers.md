# Context Discovery Answers

## Q1: Should we use Tailwind CSS v4.0 for styling (the modern standard for new SvelteKit projects)?
**Answer:** YES (Tailwind CSS v4.0 CSS-first approach maps perfectly to our colour token system using CSS custom properties).

## Q2: Should the SvelteKit project template be initialized with strict TypeScript, ESLint, and Prettier already configured?
**Answer:** YES (Strict TypeScript is required for reliable telemetry types, and Prettier/ESLint are non-negotiable for clean PR reviews).

## Q3: For mock data in this Phase 0 scaffolding stage, should we simulate the WebSocket state and SSE log streams entirely in the frontend using client-side Svelte stores and timer loops?
**Answer:** YES (Allows standalone Vercel preview links to work without a mock server, and real WS/SSE will be wired in later tasks).

## Q4: Should the scaffold include all basic placeholder Svelte pages (`/login`, `/roadmap`, `/todo`, `/orb`, `/memory`, `/logs`, `/drift`, `/commits`) and routing logic as part of this initial branch?
**Answer:** NO (Keep Task 1 clean. Placeholder pages belong to Task 9).

## Q5: Should the project layout shell, nav rail, and color variables be included in this scaffold?
**Answer:** NO (That belongs to Task 2. Task 1 is limited to framework init, Tailwind v4, build config, and mock data stores).
