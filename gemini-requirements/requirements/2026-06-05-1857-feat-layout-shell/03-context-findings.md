# Technical Context & Findings

## Codebase Status & Context
- The project is successfully scaffolded with SvelteKit and Tailwind CSS v4.0.
- Main global theme is configured in `src/routes/layout.css`.
- Real-time simulation stores are live in `src/lib/stores`.

## Proposed Layout Structure
- **Root Layout (`src/routes/+layout.svelte`)**:
  - Implements the overall shell grid layout:
    - Left Nav Rail (fixed `w-16` / `64px`, icons representing the 8 routes, tooltips on hover).
    - Main Container (fluid, flex flex-col):
      - Persistent Top Bar Header (AXIS title, status dot, uptime timer, tick rate, PAM Coherence, RPD quota).
      - Fluid Content Area (displays the child route page).
    - Right Docked Chat (fixed `w-72` / `280px` width on desktop view).
  - Responsive layout:
    - Tablet view: Collapses layout into 3 toggleable views (Dashboard, Chat, Orb).
    - Mobile view: Collapses to chat-only with top status bar.
- **Icon Set**: Install and use `lucide-svelte` to render navigation icons:
  - Cockpit: `LayoutDashboard`
  - Roadmap: `Milestone` or `Compass`
  - Todo: `ListTodo`
  - Neural Orb: `Radio` or `Globe`
  - Memory: `Database`
  - Logs: `Terminal`
  - Drift: `GitCompare`
  - Commits: `GitCommit`

## Route Directories & Placeholders
To support clean SvelteKit client-side routing without 404 errors, we will create minimal placeholder pages for all routes linked in the nav rail:
- `src/routes/roadmap/+page.svelte`
- `src/routes/todo/+page.svelte`
- `src/routes/orb/+page.svelte`
- `src/routes/memory/+page.svelte`
- `src/routes/logs/+page.svelte`
- `src/routes/drift/+page.svelte`
- `src/routes/commits/+page.svelte`
- `src/routes/login/+page.svelte`
