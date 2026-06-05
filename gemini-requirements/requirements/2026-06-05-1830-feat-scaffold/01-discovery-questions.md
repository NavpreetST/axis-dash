# Context Discovery Questions

## Q1: Should we use Tailwind CSS v4.0 for styling (the modern standard for new SvelteKit projects)?
**Default if unknown:** YES (V4 is faster, uses CSS-first configuration, and native CSS variables, which aligns perfectly with our need to map color tokens directly as CSS variables).

## Q2: Should the SvelteKit project template be initialized with strict TypeScript, ESLint, and Prettier already configured?
**Default if unknown:** YES (strict TypeScript helps model the telemetry type definitions reliably, and formatting configurations keep PR diffs clean and consistent for CodeRabbit/human review).

## Q3: For mock data in this Phase 0 scaffolding stage, should we simulate the WebSocket state and SSE log streams entirely in the frontend using client-side Svelte stores and timer loops?
**Default if unknown:** YES (this allows running and testing the entire app locally or via a Vercel preview URL without needing to manage and deploy a separate Node/FastAPI mock server process, and can be replaced with real WebSocket/SSE connections in later tasks).

## Q4: Should the scaffold include all basic placeholder Svelte pages (`/login`, `/roadmap`, `/todo`, `/orb`, `/memory`, `/logs`, `/drift`, `/commits`) and routing logic as part of this initial branch?
**Default if unknown:** NO (the suggested sprint lists placeholder routes as Task 9. Keeping the initial scaffolding PR clean and focused only on setup and configuration is better).

## Q5: Should the project layout shell, nav rail, and color variables be included in this scaffold?
**Default if unknown:** NO (the suggested sprint separates the layout shell into Task 2. Task 1 should strictly be the clean repo scaffolding, configuration files, and setup to establish the build pipeline).
