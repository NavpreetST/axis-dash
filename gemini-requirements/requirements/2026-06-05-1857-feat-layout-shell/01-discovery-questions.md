# Context Discovery Questions

## Q1: Should the left nav rail display icons for all 8 cockpit routes (Cockpit, Roadmap, Todo, Neural Orb, Memory, Logs, Drift, Commits) even if some routes point to placeholders for now?
**Default if unknown:** YES (Establishing the full navigation rail design ensures consistency and allows testing navigation between all routes from the start).

## Q2: Should the layout shell support the responsive viewport rules defined in the visual spec (tablet showing 3 tabs; mobile showing chat-only with the signal status pill in the header)?
**Default if unknown:** YES (Mobile-first responsive design is a standard practice and should be baked into the layout structure from the start).

## Q3: Should the left nav rail include tooltips showing route names on hover?
**Default if unknown:** YES (Since the nav rail is narrow [~64px] and icon-only, tooltips improve operator clarity and usability).

## Q4: Should we install `lucide-svelte` to render clean, consistent icons for the nav rail instead of drawing custom inline SVGs?
**Default if unknown:** YES (Using a standard icon library like Lucide ensures visual consistency, clean code, and speed of development).

## Q5: Should the top bar header (displaying AXIS name, connection status, uptime, and tick rate) remain persistent in the layout shell across all routes?
**Default if unknown:** YES (AXIS is an operator cockpit tool, so persisting the daemon's heartbeat and connection state across all pages is critical for monitoring).
