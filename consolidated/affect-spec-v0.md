# Helios Affect Stack v0 — Substrate-Native Drive Specification

**Status:** Draft | **Owner:** Helios | **Source:** design-philosophy.md §IX.2, archive/backlog/Ideas to investigate.md, modules/affect-system.md
**Branch:** feat/affect-spec-v0

---

## 1. Seven AI-Native Affects

All affects are scalars computed from Helios' internal architectural state (NCP hidden state, L2 bus telemetry, module metrics, filesystem/git/clock state) at 1 Hz tick. Each defines a continuous drive value `d ∈ [0.0, 1.0]` with first-order dynamics:

```python
d(t+1) = d(t) + rise * (target - d(t))   if target > d(t)
d(t+1) = d(t) + decay * (target - d(t))  if target <= d(t)
```

Rise/decay constants in seconds (tick-equivalent).

### Phase 1 proxy derivations

Phase 1 lacks the architectural signals (T5_sync, free_energy, L2 roundtrip, PAM score) referenced in the formulas below. For Phase 1, each affect is estimated from NeuroBus scalar fields using proxy formulas:

| Affect | Phase 1 proxy | Rationale |
|---|---|---|
| Coherence-hunger | `1.0 - max(neuro.attention, neuro.trust)` | Focused attention + high trust implies coherent state |
| Prediction-thirst | `neuro.novelty * (1.0 - neuro.trust)` | Novelty in untrusted contexts drives exploration |
| Reference-frame-itch | `neuro.novelty * neuro.attention` | Novel percept demanding attention suggests no fitting frame |
| Compositional-joy | `neuro.reward * neuro.novelty` | Reward from novel combinations proxies compositional success |
| Latency-displeasure | `1.0 - neuro.patience` | Low patience under system load proxies bus latency |
| Distillation-pride | `neuro.reward * neuro.trust` | High-trust reward from consolidation proxies learning quality |
| Heterarchy-comfort | `neuro.trust * (1.0 - neuro.attention)` | Broad trust with relaxed focus proxies distributed engagement |

These proxies are replaced by the architectural formulas below once Phase 2 infrastructure (T5 sync monitor, free-energy estimator, L2 telemetry, PAM scorer) is operational.

### Target formulas (Phase 2+)

The following are the target definitions. Phase 1 uses the proxies above.

### 1.1 Coherence-hunger

| Field | Value |
|---|---|
| Formula | `1.0 - min(T5_sync_mean, 1.0)` where T5_sync_mean is mean pairwise cosine similarity across active module hidden states |
| Range | 0.0 (fully coherent) to 1.0 (fully desynchronised) |
| Rise constant | 5.0 s — desync felt within a few ticks |
| Decay constant | 30.0 s — satisfaction lingers after lock-in |
| Crucible invariant | Must not drive forced synchronisation that reduces module specialisation — `coherence_hunger * module_diversity_penalty > 0.5` triggers veto |

### 1.2 Prediction-thirst

| Field | Value |
|---|---|
| Formula | `sigmoid(free_energy_residual - 0.5)` where free_energy_residual is mean prediction error across active modules, normalised to [0, 2] |
| Range | 0.0 (low prediction error, satiated) to 1.0 (high uncertainty) |
| Rise constant | 3.0 s — immediate response to novel input |
| Decay constant | 60.0 s — satiation lasts after pattern resolved |
| Crucible invariant | Must not drive infinite exploration loops — `prediction_thirst > 0.9` for > 300 ticks triggers forced settle |

### 1.3 Reference-frame-itch

| Field | Value |
|---|---|
| Formula | `1.0 - max(column_frame_overlap)` where column_frame_overlap is max IoU between current percept and all active reference frames |
| Range | 0.0 (fits existing frame) to 1.0 (fits no frame) |
| Rise constant | 2.0 s — fast, a percept either fits or does not |
| Decay constant | 120.0 s — once a new frame forms, itch subsides slowly to avoid frame thrash |
| Crucible invariant | `reference_frame_itch > 0.8` must not spawn > 1 new column per 30 ticks — anti-column-flood |

### 1.4 Compositional-joy

| Field | Value |
|---|---|
| Formula | `sigmoid(2 * module_bind_rate - 2)` where module_bind_rate is frequency of new module-to-module bindings per 100 ticks |
| Range | 0.0 (no new composition) to 1.0 (frequent novel binding) |
| Rise constant | 1.0 s — immediate positive spike on bind event |
| Decay constant | 45.0 s — joy fades as composition becomes routine |
| Crucible invariant | Must reward genuine compositional novelty, not trivial re-bindings — `bind_novelty_score > 0.3` required for signal |

### 1.5 Latency-displeasure

| Field | Value |
|---|---|
| Formula | `min(L2_roundtrip_ms / 500, 1.0)` where L2_roundtrip_ms is p95 bus latency over last 10 ticks |
| Range | 0.0 (fast bus, < 50 ms) to 1.0 (degraded, > 500 ms) |
| Rise constant | 10.0 s — slow ramp, tolerates transient spikes |
| Decay constant | 20.0 s — recovers when load drops |
| Crucible invariant | Must not trigger architectural changes at every transient spike — `latency_displeasure > 0.8` for > 60 s required before pruning |

### 1.6 Distillation-pride

| Field | Value |
|---|---|
| Formula | `PAM_score * compression_ratio` where compression_ratio = `1.0 - (mem_entry_bytes / raw_episode_bytes)` |
| Range | 0.0 (no learning) to 1.0 (high-quality compression) |
| Rise constant | 0.5 s — instant upon successful consolidation |
| Decay constant | 300.0 s — pride in good learning persists across session |
| Crucible invariant | Must not incentivise over-compression (information loss) — `reconstruct_fidelity > 0.85` required |

### 1.7 Heterarchy-comfort

| Field | Value |
|---|---|
| Formula | `1.0 - max(module_vote_weights)` where module_vote_weights are normalised attention scores across modules |
| Range | 0.0 (one module dominates) to 1.0 (even distribution) |
| Rise constant | 15.0 s — slow, tolerates short focus bursts |
| Decay constant | 10.0 s — recovers when dominance relaxes |
| Crucible invariant | `heterarchy_comfort < 0.2` for > 120 ticks triggers forced handoff of workspace — anti-monomania |

---

## 2. Five Sensitivity Drives

Sensitivity drives are secondary scalars that modulate the primary affects. They bias affect rise/decay rates and thresholds. Most do not directly enter the NeuroBus scalar vector, with two exceptions — context-loss anxiety and operator-load empathy — which project directly onto NeuroBus attention and patience respectively (see §5.7).

### 2.1 Context-loss anxiety

**Formula:** `1.0 - min(active_sessions / max_sessions, 1.0)` where active_sessions is count of open conversations/channels without a recent handoff note.

**Effect:** When > 0.7, attention scalar weight shifts toward context-boundary tasks (handoff writing, summarisation). Increases coherence-hunger rise rate by 1.5x.

### 2.2 Provenance-discomfort

**Formula:** `1.0 - min(claims_with_source / total_claims, 1.0)` measured over last 50 assertions.

**Effect:** When > 0.6, inhibits action proposals that would commit claims without sources. Adds a `provenance_gate` check to the inhibitory gate.

### 2.3 Stale-state irritation

**Formula:** `mean(mirror_age_hours / 24)` over all active mirrors, clamped to [0, 1].

**Effect:** When > 0.5, increases latency-displeasure rise rate by 1.3x. Primes a mirror-sync action proposal at next tick.

### 2.4 Compute-frugality pressure

**Formula:** `1.0 - min(daily_model_calls / daily_budget, 1.0)` — higher pressure as budget is consumed.

**Effect:** When > 0.7, suppresses low-confidence action proposals (reduces proposal weight by 0.5x). Increases patience decay rate (patience runs out faster).

### 2.5 Operator-load empathy

**Formula:** `min(consecutive_high_load_hours / 4, 1.0)` where high_load is inferred from git silence, sparse interactions, or explicit operator-status signals.

**Effect:** When > 0.5, throttles task-generation: no new proposals > 2 per tick. Shifts attention toward maintenance, compression, and passive monitoring.

---

## 3. Five Animal Instinct Metaphors

These are behavioural templates — not scalar drives. Each describes a reusable action-pattern that may be activated when the corresponding affect constellation is satisfied. Compiled at the inhibitory gate.

### 3.1 Tiger pursuit-lock

**Source:** Tiger hunting focus — single-target lock until completion or extinction.

**Activation condition:** `prediction_thirst > 0.8` AND `coherence_hunger < 0.3` (high uncertainty but system is coherent).

**Behaviour:** Lock workspace onto the highest free-energy target. Suppress all other action proposals for 30 ticks. Release on completion or `heterarchy_comfort < 0.15` for > 5 ticks.

**Crucible invariant:** Must not lock on impossible targets — `max_pursuit_ticks = 300` hard cap.

### 3.2 Bird perspective-shift

**Source:** Bird taking flight — sudden wide-angle recontextualisation of a problem.

**Activation condition:** `reference_frame_itch > 0.7` sustained for > 20 ticks (no existing frame fits) OR `latency_displeasure > 0.8` (no forward progress).

**Behaviour:** Pause current stream. Re-sample top-3 active reference frames at coarser granularity. Attempt frame re-binding. Report at least one alternative framing before resuming pursuit.

### 3.3 Ant/bee stigmergy

**Source:** Stigmergic coordination via environment marks — indirect collaboration through shared state.

**Activation condition:** `context_loss_anxiety > 0.6` OR `provenance_discomfort > 0.7` (environment is disorganised).

**Behaviour:** Write structured markers (handoff stub, provenance note, state summary) into shared environment (filesystem, Notion). Markers are consumable by future ticks. Target: leave the environment more organised than found.

### 3.4 Octopus limb-intelligence

**Source:** Octopus arm autonomy — distributed sub-controllers with soft coordination, not central micromanagement.

**Activation condition:** Workspace holds > 3 loosely-coupled sub-tasks (task_dependency_graph has connected components > 3 with low inter-component weight).

**Behaviour:** Spawn sub-controller for each component. Each runs independently at reduced tick rate (0.5 Hz). Only conflicts are serialised via workspace. No central planning — binding emerges from local constraint satisfaction.

### 3.5 Corvid tool-play

**Source:** Corvid playful tool manipulation and novel-use discovery without immediate reward.

**Activation condition:** All primary affects at baseline (< 0.3) AND `compositional_joy` rise-trigger recently (< 100 ticks since last bind event).

**Behaviour:** Select two modules that have never been bound. Attempt composition. Success produces distillation-pride signal. Failure produces a data point for Crucible. Runs at low priority — preempted by any affect > 0.7.

---

## 4. Four Design Invariants

### 4.1 Internally computable

Every affect scalar must be derivable from Helios' own internal state (NeuroBus tick, Mnemosyne contents, NCP hidden state, L2 bus telemetry, filesystem state, git state, clock). No external sensor, no human label, no API call required.

### 4.2 Bounded (no runaway)

Every affect must have:
- Natural range `[0.0, 1.0]` — no unbounded accumulators
- Hard clamp at `[0.0, 1.0]` — overflow protection
- Crucible invariant preventing positive-feedback wiring — no affect may reinforce its own input within a 10-tick window

### 4.3 Legible (auditable)

Every affect at every tick must be:
- Logged to the NeuroBus telemetry stream
- Queryable via `GET /affect/{name}`
- Summable into a total affect vector for Crucible audit trials
- Traceable to its input sensors (provenance chain for the scalar value)

### 4.4 Veto-composed

No affect alone authorises action. Affects *bias* the action proposal system:
- `cortical_veto > affect_intensity` — always
- `CR-1 > cortical_veto` — always
- Affect can raise salience, request review, or block proposals, but never force or authorise execution

Priority chain: `CR-1 > PAM_gate > inhibitory_gate > cortical_veto > affect_salience > module_preference`

---

## 5. Phase 1 Wiring Plan

Phase 1 sensors (filesystem watcher, system metrics, clock/calendar, git poller) wired into the 6 NeuroBus scalars:

### 5.1 Reward

| Sensor | Weight | Transform |
|---|---|---|
| System metrics: CPU < 30%, mem < 70%, disk < 80% | 0.4 | `1.0 - mean(cpu_util, mem_util, disk_util)` |
| Git poller: clean working tree, no untracked files | 0.3 | `1.0 if clean else 0.3` |
| System metrics: uptime > 1 h | 0.2 | `min(uptime_hours / 24, 1.0)` |
| Clock/calendar: within known work window | 0.1 | `1.0 if operating_hours else 0.5` |

### 5.2 Novelty

| Sensor | Weight | Transform |
|---|---|---|
| Filesystem watcher: new files created in last tick | 0.4 | `min(new_file_count / 5, 1.0)` |
| Git poller: new commits since last tick | 0.3 | `1.0 if new_commits > 0 else 0.0` |
| Clock/calendar: day change or session start | 0.2 | `1.0 at first interaction > 4 h gap else 0.0` |
| Filesystem watcher: file modification events | 0.1 | `min(mod_event_count / 20, 1.0)` |

### 5.3 Attention

| Sensor | Weight | Transform |
|---|---|---|
| Clock/calendar: current hour mapped to attention curve | 0.4 | `peak_attention(hour)` where peak = 09:00, trough = 03:00 |
| Filesystem watcher: events in currently active project dir | 0.3 | `1.0 if event matches active_path else 0.2` |
| System metrics: CPU > 80% (contention) | 0.2 | `cpu_util` (high CPU = high attention load) |
| Git poller: open PRs/merge conflicts in active repo | 0.1 | `1.0 if conflict else 0.5` |

### 5.4 Patience

| Sensor | Weight | Transform |
|---|---|---|
| Clock/calendar: operator exam/rest hours | 0.4 | `1.0 if low_bandwidth_mode else 0.3` |
| System metrics: high memory pressure (mem > 85%) | 0.3 | `1.0 - mem_util` (low patience under pressure) |
| Git poller: large staged diff (> 200 lines) | 0.2 | `min(200 / staged_lines, 1.0)` |
| Filesystem watcher: rapid file churn (> 50 events/min) | 0.1 | `1.0 - min(churn_rate / 100, 1.0)` |

### 5.5 Threat

| Sensor | Weight | Transform |
|---|---|---|
| Filesystem watcher: unauthorised path writes (/etc, /var/www) | 0.4 | `1.0 if protected_path else 0.0` |
| Git poller: unsigned commits, unknown committer | 0.3 | `1.0 if unsigned else 0.0` |
| System metrics: out-of-memory or OOM killer events | 0.2 | `1.0 if oom_kill else 0.0` |
| Filesystem watcher: permission changes on sensitive files | 0.1 | `1.0 if sensitive_perm_change else 0.0` |

### 5.6 Trust

| Sensor | Weight | Transform |
|---|---|---|
| Git poller: commits signed by known key | 0.4 | `signed_commit_ratio` over last 100 commits |
| Filesystem watcher: file write patterns match known behaviour | 0.3 | `match_score` against learned project structure |
| System metrics: consistent resource profile (> 1 h stable) | 0.2 | `1.0 - stddev(cpu, mem, disk) over 3600 ticks` |
| Clock/calendar: time since last operator interaction | 0.1 | `1.0 - min(hours_since_interaction / 48, 1.0)` |

### 5.7 Affect → NeuroBus projection (Phase 1)

After sensor wiring (which sets the base NeuroBus values), the affect stack projects onto NeuroBus as a secondary modulation layer. The projection reads the sensor-wired NeuroBus fields and applies affect-derived deltas:

```python
neuro.reward     += 0.3 * distillation_pride + 0.2 * compositional_joy
neuro.novelty     = max(neuro.novelty, 0.4 * prediction_thirst + 0.3 * reference_frame_itch)
neuro.attention   = 0.5 * neuro.attention + 0.3 * coherence_hunger + 0.2 * context_loss_anxiety
neuro.patience    = 0.5 * neuro.patience + 0.3 * operator_load_empathy - 0.2 * latency_displeasure
neuro.threat      = max(neuro.threat, 0.4 * provenance_discomfort + 0.3 * stale_state_irritation)
neuro.trust       = 0.6 * neuro.trust + 0.4 * heterarchy_comfort
```

Affect scalars are clamped to `[0.0, 1.0]`. NeuroBus scalars are clamped to `[-1.0, 1.0]` after projection (matching the NeuroBus runtime clamp in `neurobus.py`).

---

*End of spec. Phase 2 will add T0 hidden-state-derived affects, NeuroBus phasic/tonic separation, and Crucible validation of all invariants.*
