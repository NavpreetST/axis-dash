# Expert Requirements Answers

## Q1: For tablet devices, should the header display a tab-switcher enabling the operator to toggle between the Dashboard, Chat, and Orb views?

**Answer:** YES (Matches the tablet specification exactly to divide the viewport elements into 3 tabbed panels).

## Q2: Should the bearer token auth route guard (checking localStorage for `HELIOS_TOKEN` and redirecting to `/login` if missing) be implemented in the root `+layout.svelte` as part of this shell task?

**Answer:** YES (Lock all routes except `/login` from the start. Do not defer this to Task 8).

## Q3: Should the left nav rail highlight the active route using our primary accent color (`accent/cyan`) to indicate the active screen?

**Answer:** YES (Essential operator feedback. Cyan is the primary accent - use it to highlight the active route).

## Q4: Should the Aegis Chat component be moved from `+page.svelte` into the global `+layout.svelte` shell (so it remains docked on the right and persistent across all pages)?

**Answer:** YES (Operator must be able to chat with Aegis from any screen. Move the chat component to the shell now).

## Q5: Should the responsive collapse transitions (e.g. sliding out the chat panel on mobile) use basic CSS transitions for now, deferring the installation of advanced motion libraries like Motion/GSAP?

**Answer:** YES (Keep it lean. Motion will come in a later polish pass).
