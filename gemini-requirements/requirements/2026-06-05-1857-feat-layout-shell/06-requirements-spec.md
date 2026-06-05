# Requirements Specification: Task 2 (feat/layout-shell)

## 1. Problem Statement & Solution Overview
This requirement covers the design, styling, security, and responsive structure of the global **AXIS (Aegis eXecution Intelligence Surface)** app shell. It moves the chat terminal, status indicators, and navigation elements from individual page scope into the global layout shell to enable persistent access. It also sets up standard placeholders for all linked routes to allow client-side page routing without errors.

## 2. Functional Requirements
- **App Layout Shell**:
  - Left-docked Icon Navigation Rail (fixed `w-16` / `64px` width) displaying the 8 cockpit routes.
  - Persistent Top Bar Header displaying status signals (connection, uptime, tick rate, PAM, and RPD).
  - Main view (fluid width) displaying child page routes.
  - Right-docked Aegis Chat terminal (fixed `w-72` / `280px` width) that remains persistent and readable across all routes.
- **Route Guard Protection**:
  - Active check in Svelte's lifecycle on mount: checks if a valid `HELIOS_TOKEN` exists in `localStorage`.
  - Redirects unauthorized traffic to `/login` immediately.
  - Skips route guard check for `/login` page itself to avoid infinite redirect loops.
- **Visual Spec & Theme**:
  - Highlights active route icon in the nav rail with the primary accent color (`accent/cyan`).
  - Implements tooltips displaying the destination route name on hover.
  - Fluid layout adapting to:
    - Desktop: Grid showing rail, header, main content, and docked chat.
    - Tablet: Tabs header permitting the operator to switch between Dashboard, Chat, and Orb panels.
    - Mobile: Chat-only dashboard panel with the telemetry status pill in the top header.
- **Dependencies**:
  - Install `lucide-svelte` to render clean, consistent icons.

## 3. Technical Requirements & File Paths
- **Route Layout (`src/routes/+layout.svelte`)**:
  - Implements the grid shell.
  - Houses the persistent chat drawer, nav rail, and status header.
  - Integrates the auth check guard.
- **Placeholders**:
  - Minimal `+page.svelte` files showing page name under `src/routes/roadmap/`, `src/routes/todo/`, `src/routes/orb/`, `src/routes/memory/`, `src/routes/logs/`, `src/routes/drift/`, `src/routes/commits/`, and `src/routes/login/`.
- **Modified Cockpit Page (`src/routes/+page.svelte`)**:
  - Strip the Aegis Chat component out (since it is moved to `+layout.svelte`) and expand the telemetry and Signal state components to fill the layout space.

## 4. Acceptance Criteria
- [ ] `lucide-svelte` dependency installed successfully.
- [ ] Nav rail shows all 8 routes, highlighting the active one in cyan, and displays tooltips on hover.
- [ ] Aegis Chat is persistent on the right side and usable from any routed subpage.
- [ ] Root route guard redirects to `/login` if `HELIOS_TOKEN` is missing, and permits loading of other routes when the token exists.
- [ ] Tablet view collapses panels into a 3-tab layout switcher; mobile view collapses into a chat-only viewport.
- [ ] Build compiles (`npm run build`) and passes linter checks (`npm run lint`).
