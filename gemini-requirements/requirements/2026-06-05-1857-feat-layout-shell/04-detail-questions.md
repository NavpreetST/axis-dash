# Expert Requirements Questions

## Q1: For tablet devices, should the header display a tab-switcher enabling the operator to toggle between the Dashboard, Chat, and Orb views?

**Default if unknown:** YES (This aligns with the tablet specification to divide the screen elements into 3 tabbed panels).

## Q2: Should the bearer token auth route guard (checking localStorage for `HELIOS_TOKEN` and redirecting to `/login` if missing) be implemented in the root `+layout.svelte` as part of this shell task?

**Default if unknown:** YES (Securing all routes except `/login` from the beginning matches the specified routing rules).

## Q3: Should the left nav rail highlight the active route using our primary accent color (`accent/cyan`) to indicate the active screen?

**Default if unknown:** YES (Provides essential visual feedback for operator navigation).

## Q4: Should the Aegis Chat component be moved from `+page.svelte` into the global `+layout.svelte` shell (so it remains docked on the right and persistent across all pages)?

**Default if unknown:** YES (Allows the operator to chat with Aegis while viewing logs, commits, memory, or drift screens, matching the reference visual mockup).

## Q5: Should the responsive collapse transitions (e.g. sliding out the chat panel on mobile) use basic CSS transitions for now, deferring the installation of advanced motion libraries like Motion/GSAP?

**Default if unknown:** YES (Keeps initial code simple and performs fast without importing large animation frameworks immediately).
