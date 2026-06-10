# Helios Neural Orb

## Purpose

Single source of truth for the entire Helios AXIS cognitive state. The orb
aggregates data from every known source — runtime sensors, the Helios bridge,
Supabase, GitHub, Notion, and planned roadmap items — into one typed contract.
Visual layers (Three.js canvas, inspector panels) read from this contract;
they never fetch or derive their own state.

## File Structure

```
src/lib/orb/
├── types.ts          # All type contracts (no runtime code)
├── mockState.ts      # Factory returning a full HeliosOrbState with mock data
├── README.md         # This file
```

Phase 1 will add `transform.ts` (bridge JSON → orb state mapper).
Phase 2 will add `store.ts` (Svelte writable with polling).
Phases 3–5 will add visual components (inspector, canvas, controls).

## Design Principles

1. **Every field has a source.** No value enters the orb without an `OrbSource`
   annotation telling you whether it came from the live bridge, a mock, a
   planned item, or is unknown. This prevents "magic data" — every pixel on
   screen can be traced back to its origin.

2. **Unknown is null, not zero.** If a value is missing, it is `null` (or
   `undefined` for optional fields). Never `0`, `false`, or an empty string.
   This lets visual layers distinguish "no data" from "data is zero".

3. **No visual logic in state.** The orb contract is pure data — no Three.js
   objects, no shader uniforms, no DOM references. Visual layers import the
   contract and derive their own presentation.

4. **Completeness over convenience.** The contract models every subsystem
   the orb can display, even if the data source hasn't been wired yet.
   Unavailable subsystems show `source: "unknown"` with `null` values.

## Anti-Generic Protocol

The orb does NOT use generic "key-value" or "property bag" patterns.
Every subsystem has a dedicated interface with typed fields. This makes
renames, deprecations, and IDE refactoring safe. If a field is unused,
remove it — don't bury it in a `Record<string, unknown>`.

## Build Phases

| Phase | Deliverable                  | Visuals           |
| ----- | ---------------------------- | ----------------- |
| 0     | Types, mockState, stubs      | None              |
| 1     | Bridge transform + store     | Text overlay only |
| 2     | Inspector panel (orb/2d)     | SVG wireframe     |
| 3     | Particle system (orb/core)   | Three.js points   |
| 4     | Connection lines + pulse     | Three.js lines    |
| 5     | Full orb canvas (orb/canvas) | Three.js renderer |
