# Context Discovery Answers

## Q1: Should the left nav rail display icons for all 8 cockpit routes (Cockpit, Roadmap, Todo, Neural Orb, Memory, Logs, Drift, Commits) even if some routes point to placeholders for now?
**Answer:** YES (Show all routes from the start, even if they point to placeholder pages. Design consistency is important).

## Q2: Should the layout shell support the responsive viewport rules defined in the visual spec (tablet showing 3 tabs; mobile showing chat-only with the signal status pill in the header)?
**Answer:** YES (Do it now, not as a patch later. Baked directly into the root app layout structure).

## Q3: Should the left nav rail include tooltips showing route names on hover?
**Answer:** YES (A 64px icon-only nav rail needs hover tooltips for operator clarity).

## Q4: Should we install `lucide-svelte` to render clean, consistent icons for the nav rail instead of drawing custom inline SVGs?
**Answer:** YES (Using `lucide-svelte` for clean, consistent, and fast development).

## Q5: Should the top bar header (displaying AXIS name, connection status, uptime, and tick rate) remain persistent in the layout shell across all routes?
**Answer:** YES (This is a heartbeat monitor, status must always be visible).
