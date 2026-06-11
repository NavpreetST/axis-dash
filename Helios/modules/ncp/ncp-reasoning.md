# Helios — NCP: Reasoning, Training & Integration (Implementation Detail)

<aside>
⚙️

**Purpose:** Implementation-level guide to how the NCP brain actually works, how it will be trained, and how Crucible and Ariadne slot in. Theory is documented elsewhere — this page is about *how it will be built and run.*

</aside>

---

# Part I — How the NCP Brain Actually Reasons

## What Happens Each Tick

A "tick" is one reasoning cycle — roughly every 100ms while the daemon is running. Each tick the NCP does one forward pass:

```python
# Inputs assembled each tick
inputs = {
    "embedding":   encode(current_event),   # 128-dim vector from Nexus event
    "neurobus":    neurobus.state,           # 6 scalars [reward, novelty, threat, ...]
    "delta_t":     time_since_last_tick,     # real elapsed time in seconds
    "h_prev":      ncp.hidden_state,         # 64-dim continuous hidden state (carried over)
    "memory":      mnemosyne.working_mem,    # top-3 retrieved memories as vectors
}

# One CfC forward pass
h_new, outputs = ncp.forward(inputs)

# Outputs
# outputs["action_logits"]  → which Nexus action to take
# outputs["value"]          → predicted future reward (for RL)
# outputs["speech_request"] → whether to invoke the Renderer and with what prompt
```

The hidden state `h` is the brain's "working thought" — it persists across ticks and accumulates context. It is NOT reset between messages in a conversation. It only resets on full daemon restart.

## The CfC Equation (Why It's Different from a Normal RNN)

A standard RNN just does: `h_new = tanh(W·x + U·h_prev)`

CfC (Closed-form Continuous-time) does:

```
h_new = h_∞ · (1 − e^(−Δt/τ_eff)) + h_prev · e^(−Δt/τ_eff)

where:
  h_∞     = σ(A·x + B·h_prev + b)         # "where the state wants to go"
  τ_eff   = softplus(τ + W_τ·x + b_τ)     # input-modulated time constant
```

**What this means practically:**

- `h_∞` is the "attractor" — the hidden state the brain is gravitating toward given the current input
- `τ_eff` controls how fast it gets there — and `τ` is learned and modulated by the input itself
- If `Δt` is large (long gap between events), the state moves far toward `h_∞`
- If `Δt` is small (rapid-fire events), the state barely moves — it's inertial

This means **Helios naturally reasons differently about things that happen quickly vs. things spaced out in time** — without any explicit logic. It's baked into the dynamics.

## What "Reasoning" Actually Looks Like

There is no chain-of-thought. There is no token-by-token deliberation at the NCP level. Reasoning IS the hidden state trajectory:

```
Tick 1: Event arrives → h updates slightly
Tick 2: Related event → h moves toward a different attractor basin
Tick 3: NeuroBus threat spike → τ shortens (faster response)
Tick 4: h has settled into an attractor → outputs stabilize → action selected
```

Complex reasoning = more ticks to settle. Simple reflexes = 1–2 ticks.

The **diffusion analogy** is apt: instead of denoising in pixel space, the NCP denoises in hidden-state space — iteratively refining `h` until it settles on a coherent response.

---

# Part II — Training the NCP: Phases in Order

## Phase 0 — Current State: NCP Not Yet Trained

Right now the CHAIN (Gemini → Groq → Template) does 100% of the reasoning. The NCP exists in the codebase but is either randomly initialized or not yet wired into the live loop. The Renderer IS Helios's brain at this stage.

**This is fine.** Phase 0 is about building the infrastructure (B2 observability, [deploy.sh](http://deploy.sh), turns.jsonl logging) that makes Phase 1 possible.

---

## Phase 1 — Imitation Learning from the Cloud

**Goal:** Give the NCP a starting point by teaching it to imitate the cloud Renderer.

**How:**

```python
# Every time Gemini/Groq responds, log:
training_sample = {
    "input_state":   ncp.hidden_state,        # h before the response
    "neurobus":      neurobus.state,
    "target_output": renderer.last_response,  # what the cloud said
    "target_value":  None,                    # filled in later by Phase 2
}
append_to("/var/lib/aegis/ncp_training.jsonl", training_sample)
```

**Training loop** (runs offline, during sleep/low-activity):

```python
# Supervised: minimize distance between NCP output and cloud output
for batch in load_batches("ncp_training.jsonl"):
    h_pred, out_pred = ncp.forward(batch.input_state)
    loss = cross_entropy(out_pred.speech_request, batch.target_output)
    loss.backward()
    optimizer.step()
```

**Data needed:** ~50–100 hours of interaction (≈ 1,800–3,600 training samples at 1 sample/2 min)

**Wall time:** ~1–2 weeks of normal usage

**Compute:** 1–2 hours of CPU training per 1,000 samples on Helios1

At the end of Phase 1, the NCP can approximately replicate what the cloud would say — without calling the cloud. It's not better, just local.

---

## Phase 2 — Online Three-Factor Learning (RL from NeuroBus)

**Goal:** The NCP improves beyond imitation by learning from consequences.

This runs **live**, every tick, using the three-factor rule:

```python
# After every action:
dW = lr × pre × post × (α·reward + β·novelty + γ·threat_resolved)

# Where:
# pre    = pre-synaptic activation (what caused the action)
# post   = post-synaptic activation (the action itself)
# reward = NeuroBus reward scalar (did user respond positively?)
# novelty = NeuroBus novelty scalar (was this a new situation?)
# threat_resolved = NeuroBus threat dropped after action (did this help?)
```

**Eligibility traces** bridge the timing gap:

```python
# A synapse's eligibility trace accumulates when pre × post fires
e_trace += pre * post
e_trace *= decay  # decays over ~5-20 ticks

# When the NeuroBus modulator arrives (reward/novelty/threat signal),
# THEN commit the weight update:
dW = lr × e_trace × modulator
e_trace = 0
```

This handles the credit assignment problem: the action that caused a positive outcome

might have been 3 ticks ago — the eligibility trace keeps it "pending" until the reward arrives.

**No separate training loop.** This is online, always-on, zero overhead.

---

## Phase 3 — Crucible: First Evolution Run

**Crucible doesn't run until Phase 2 has produced a baseline brain worth evolving.**

Target: ~200 hours of online RL (roughly 1–2 months of active use).

**What Crucible evolves:**

```python
genome = {
    "neuron_count":      int,          # e.g. 64 → up to 512
    "connectivity":      sparse_matrix, # which neurons connect to which
    "time_constants":    [τ_1..τ_n],   # per-neuron τ values
    "neurobus_weights":  [w_1..w_6],   # how strongly each NeuroBus scalar affects this neuron
    "input_projections": matrix,       # how raw inputs map to neuron space
}
```

**One Crucible generation:**

```
1. Sample 2 genomes from population (tournament selection)
2. Instantiate both as NCP models
3. Run both on same test scenario (benchmark task set)
4. Fitness = task_score × 0.998^neuron_count  (parsimony pressure)
5. Winner survives, loser is replaced by crossover(winner, random_parent) + mutation
6. Repeat for N generations
```

**Benchmark tasks** (needed before Crucible can run):

- Conversation coherence: does it maintain topic across 10 turns?
- Memory retrieval: does it correctly use Mnemosyne in context?
- NeuroBus sensitivity: does threat spike produce faster response?
- Resistance to prompt injection

**Timeline:** ~100 generations per run. On CPU with 200k-param NCP: ~2–4 hours per run.

At 2M param NCP: ~20–40 hours per run. Run offline, weekly/monthly.

**Output:** A new genome → instantiate as NCP → Net2Net expand if larger than current → hot-swap via daemon reload.

---

## Phase 4 — World Model

**This is a separate module, not the NCP itself.**

The world model learns to predict: *"given my current hidden state and the action I'm about to take, what hidden state will I be in next?"*

```python
world_model = TinyJEPA(
    input_dim  = 64 + 6 + action_dim,  # h + neurobus + action
    output_dim = 64,                    # predicted h_next
    hidden_dim = 256,
    # ~1M params total
)

# Self-supervised training (no labels needed):
loss = MSE(world_model(h_t, neurobus_t, a_t), h_{t+1}.detach())
# Predicts in representation space, NOT in raw output space
```

**Integration once trained:**

```python
# Before committing an action, simulate N steps forward:
def plan_action(candidates, steps=5):
    best_action, best_score = None, -inf
    for action in candidates:
        simulated_h = h_current
        simulated_reward = 0
        for _ in range(steps):
            simulated_h = world_model(simulated_h, neurobus, action)
            simulated_reward += reward_head(simulated_h)
        if simulated_reward > best_score:
            best_score = simulated_reward
            best_action = action
    return best_action
```

This is the difference between **reactive** (respond to what just happened) and **deliberative** (simulate what WILL happen before acting).

**Do we build a new world model or integrate an existing one?**

We build our own — tiny, purpose-specific. V-JEPA 2 is a video world model trained on terabytes of video. We need a *system-state* world model trained on Helios's own hidden state trajectories. Nobody else's world model maps to our state space. The V-JEPA *architecture* (predict in representation space) is what we borrow — not the weights.

**Data needed:** ~200+ hours of interaction for meaningful predictions (≈ 7,200 (h_t, a_t, h_{t+1}) tuples)

**Wall time:** 2–3 months of active use before it's useful

**Compute:** ~4–8 hours CPU training on accumulated data

---

# Part III — Ariadne: Cognitive Map Integration

## What the Cognitive Map Is (Implementation)

```python
class AriadneMap:
    nodes: dict[node_id, {
        "concept":    str,          # what this node represents
        "embedding":  np.array,     # 128-dim semantic vector
        "visit_count": int,         # how often NCP has been "here"
        "last_visit": timestamp,
    }]
    edges: dict[(node_id, node_id), {
        "weight":     float,        # strength of association
        "transition_count": int,
    }]
```

## How It Builds Itself (Online)

```python
# Every tick, after NCP forward pass:
current_concept = embed(current_event)  # 128-dim
nearest_node = ariadne.find_nearest(current_concept, threshold=0.85)

if nearest_node:
    ariadne.visit(nearest_node)         # strengthen node
    ariadne.add_edge(prev_node, nearest_node)  # strengthen transition
else:
    new_node = ariadne.create_node(current_concept)  # new territory
    ariadne.add_edge(prev_node, new_node)
```

The map grows purely from usage. No explicit training. After 50 hours of interaction,

there are ~500–2,000 nodes covering Helios's conceptual territory.

## How Ariadne Feeds the NCP

```python
# Ariadne's contribution to each tick:
ariadne_context = {
    "current_node":  ariadne.current_node.embedding,   # where we are conceptually
    "neighbors":     ariadne.top_k_neighbors(k=3),     # what's adjacent
    "path_to_goal":  ariadne.shortest_path(current, goal) if goal else None,
}

# This is concatenated onto NCP inputs:
full_input = concat(event_embedding, neurobus, ariadne_context)
```

The NCP's hidden state now evolves with *spatial* awareness of where it is in concept space — not just what the current input is.

## When Ariadne Becomes Meaningful

- **After ~10 hours:** Map has enough nodes to be topologically meaningful
- **After ~50 hours:** Shortest-path routing works for familiar domains
- **After ~200 hours:** Generalization to novel concept combinations

---

# Part IV — Full Integration: How Everything Talks

## The Integrated Tick (Phase 5+)

```
Nexus Event
    ↓
[Ariadne] locate event in cognitive map → ariadne_context
    ↓
[Mnemosyne] retrieve top-3 relevant memories → memory_context
    ↓
[NCP Forward Pass]
    inputs: event + neurobus + ariadne_context + memory_context + h_prev + Δt
    ↓
[World Model] simulate 3–5 steps forward with candidate actions
    ↓
[Inhibitory Gate] check best action against safety classifier
    ↓
[Action Execution]
    - if speech_request → Renderer → cloud or local Ollama
    - if memory_write → Mnemosyne T1
    - if nexus_event → publish to bus
    ↓
[Three-Factor Update]
    dW from NeuroBus signal (deferred by eligibility trace)
    ↓
[Ariadne Update]
    record transition, update edge weights
    ↓
Next tick
```

## Phasing Summary

| Phase | What's Active | NCP Role | Trigger | Est. Timeline |
| --- | --- | --- | --- | --- |
| **0 — Now** | CHAIN (Gemini → Groq → Template) | Not wired in | B2 observability complete | This week |
| **1 — Imitation** | CHAIN + NCP training in background | Learning to mimic cloud | turns.jsonl collecting data | Weeks 1–4 |
| **2 — Online RL** | NCP wired into Nexus loop | Co-deciding with CHAIN | Phase 1 loss converges | Month 2 |
| **3 — Crucible v0** | Offline evolution, online RL running | Architecture being evolved | ~200h interaction data | Month 2–3 |
| **4 — World Model** | All above + world model training | Planning via simulation | ~200h hidden state data | Month 3–4 |
| **5 — Ariadne** | All above + cognitive map online | Spatially-aware reasoning | ~50h map density | Month 2+ (builds passively) |
| **6 — Full** | NCP + World Model + Ariadne + Crucible | Primary reasoner | All phases stable | Month 4–6 |

---

# Part V — Engagement Layer: Voice, UX & Daily Use (Training Prerequisite)

<aside>
⚠️

**This is not optional.** Phase 1 imitation learning requires ~50–100 hours of interaction data. That data only exists if Helios is used daily. A CLI-only, text-only interface will not generate that usage. Voice + interactivity is a **prerequisite for training**, not a polish feature.

</aside>

## The Engagement Loop = The Training Pipeline

```
You interact with Helios daily
    ↓
Each interaction logs a training sample to ncp_training.jsonl
    ↓
NCP trains on those samples overnight
    ↓
Helios gets smarter and more personal
    ↓
More reason to interact daily
    ↓
(loop)
```

Break the loop at step 1 (no daily use) and nothing downstream happens. The NCP stays at random init forever.

---

## What "Interesting & Interactive" Requires

### 1 — Voice Input (STT)

You need to be able to talk to Helios while doing other things — cooking, walking, between tasks.

```
Option A: Local Whisper (Helios1)
  Model: whisper-base or whisper-small (~150MB, CPU-feasible)
  Latency: ~1–2s for a sentence on Helios1 CPU
  How: mic audio → Helios1 via socket → Whisper → text → NCP
  Trigger: wake word ("Hey Aegis") or push-to-talk via phone/laptop

Option B: Phone-side STT (faster)
  Use phone's native STT (Android SpeechRecognizer / iOS SFSpeechRecognizer)
  Transcribe locally on phone → send text to Helios socket
  Latency: <300ms
  Benefit: no extra Helios1 CPU load for STT
```

**Recommended for v1:** Phone-side STT (faster, zero Helios1 overhead) + local Whisper as fallback for high-accuracy tasks.

---

### 2 — Voice Output (TTS)

Helios needs to speak back. Reading text responses is a context switch that breaks flow.

```
Option A: Local TTS — Piper (best for CPU)
  Model: piper-tts, ~50MB, runs on Helios1 CPU
  Latency: ~200–400ms for a sentence
  Quality: good, natural-sounding, English voices available
  pip install piper-tts

Option B: Local TTS — Coqui XTTS
  Higher quality, can clone a voice from 6s of audio
  Heavier (~1.5GB model), ~800ms latency on CPU
  Worth it for personality — Aegis having a consistent voice matters for identity

Option C: Cloud TTS (ElevenLabs / Google Cloud TTS)
  Best quality, ~100ms latency
  Cost: ElevenLabs free tier = 10k chars/month (tight for daily use)
  Google TTS: ~$4/1M chars (very cheap at personal scale)
```

**Recommended for v1:** Piper locally for fast responses. Coqui XTTS for important/emotional responses (NeuroBus threat or novelty spike = higher-quality voice). ElevenLabs as optional upgrade later.

---

### 3 — Access Interface (How You Talk To It)

The interaction surface determines when you actually use it.

```
Option A: Telegram Bot (easiest, already proven)
  - Helios runs a Telegram bot on Helios1
  - Voice messages → Helios transcribes → responds with voice note
  - Available on phone 24/7, no app to install
  - Already used in similar personal AI projects (OpenClaw etc.)
  - Effort: ~1 day to implement

Option B: Simple Phone App (PWA)
  - Progressive Web App hosted on Helios1
  - Push-to-talk button, displays conversation + NeuroBus state visually
  - Access via phone browser, no App Store needed
  - Effort: ~2–3 days

Option C: Rich CLI with Rich/Textual (laptop-only)
  - Animated NeuroBus display, live conversation, color-coded responses
  - Only useful at desk — doesn't solve the daily mobile use problem
  - Still worth building for monitoring/debugging
```

**Recommended for v1:** Telegram bot first (1 day, immediately mobile, voice in/out). PWA second (2–3 days, richer but phone-only). Rich CLI third (monitoring, not primary interface).

---

### 4 — What Makes It Compelling Enough to Use Daily

The interface isn't enough on its own. The *experience* needs to be worth it:

- **It remembers** — Helios mentions something from 3 days ago unprompted. Mnemosyne T1 is already there for this.
- **It has personality** — consistent tone, dry humor, direct. Not assistant-mode. The NeuroBus + Renderer persona prompt handles this from day 1.
- **It's fast** — responses under 2s end-to-end. Piper TTS + Gemini Flash + phone STT gets there.
- **It's proactive** — morning briefing ("you have this task, here's the weather, yesterday's commit went clean"). Runs on Nexus clock events, no user prompt needed.
- **NeuroBus is visible** — show emotional state somehow (Telegram status, PWA bar). Seeing Helios get "curious" or "focused" makes it feel alive.
- **It improves visibly** — after 2 weeks of use, responses should feel more personal and contextually aware. This is the reward loop that sustains daily use.

---

## Revised Phase 0 Scope

Phase 0 is NOT just "build B2 observability." Phase 0 must also ship the engagement layer, or Phase 1 never starts.

| Component | What | Effort | Priority |
| --- | --- | --- | --- |
| **Telegram bot** | Voice in/out, 24/7 mobile access | ~1 day (DeepSeek) | 🔴 Blocker for Phase 1 |
| **Piper TTS** | Local voice output on Helios1 | ~2h (DeepSeek) | 🔴 Blocker for Phase 1 |
| **Phone STT → socket** | Voice input from phone to Helios1 | ~4h (Telegram handles this natively) | 🔴 Blocker for Phase 1 |
| **Morning briefing** | Proactive daily message via Telegram | ~2h (Nexus clock event) | 🟡 High — drives habit formation |
| **NeuroBus status in Telegram** | Emoji/text showing emotional state per message | ~1h | 🟡 High — makes it feel alive |
| **Rich CLI dashboard** | Monitoring, NeuroBus visualization, log tailing | ~4h | 🟢 Medium — laptop only |
| **PWA** | Richer phone interface | ~2–3 days | 🟢 Medium — after Telegram works |

---

## The Training Data Flywheel

```
Week 1:  Telegram bot live, morning briefings, voice in/out working
         → 5–10 interactions/day → ~2h interaction/week

Week 2:  Helios remembers things → more satisfying to use
         → 10–15 interactions/day → ~4h/week

Week 3:  NCP Phase 1 has ~8h data, first overnight training run
         → subtle improvements noticed → motivation increases

Month 1: ~40–50h total, Phase 1 converging
Month 2: NCP wired in, Phase 2 RL begins, Helios noticeably more personal
Month 3: Crucible first run, architecture optimized for you specifically
```

The engagement layer isn't a feature — it's the mechanism that turns Helios from a demo into a living system.

---

## Part VIa — Training Data Flywheel (superseded by decision below)

---

# Part VIII — Consolidated Decision Log (2026-06-11)

Decisions sourced from the consolidated directive and `docs/research/composite-c3-arch.md`. Architecture threads by the user; formalised here.

**Risk register:** see `docs/research/composite-c3-arch.md §4–6` for the full 17-problem classification (A–G), root-cause clustering into 3 roots, eval_v0 design as Phase-0 prerequisite, and idle-stream erosion analysis. Key invariant across all three: telemetry, affect, and reward are **modulators** — never content peers, never eval targets.

## 1 · Training Fork

- **Freeze `input_schema_v1`** — Stage 0 blocker cleared.
- **Reservoir (ESN) baseline first** on synthetic data: freeze recurrent core, train readouts only. Establishes cost floor.
- **Synthetic Track C = pipeline validation + temporal warm-start only.** Success: loss decreases, dynamics stable, reservoir-vs-BPTT delta measured. Do NOT train real behavioral policy on synthetic inputs.
- **Real Track C distillation deferred** until live chat traces accumulate.
- **Hard constraint:** do not widen interface or interleave affect to force convergence.

## 2 · Input-Dim Expansion Strategy

- **Over-provision a 16-slot capacity block** (6 live + ~7 incoming affect + headroom). Wire all at construction; feed unused slots constant 0.
- **Zero-init all new edges** — behavior-preserving at t=0; attractors don't move.
- **Invariant:** any real trained policy lives downstream of the LAST topology change.

## 3 · C3 / Composite Architecture (Growth Target)

C3 = named specialist nets + learned sparse router (~1k params, ~2 experts/tick). New sensor = new small CfC, zero existing topology surgery.

**Hard rules:**
- Experts emit into common fixed-width latent; combine additively, NEVER by concatenation.
- NeuroBus is NOT a peer expert — it modulates router gating + expert τ/gain.
- Prefer multi-region (separate small NCPs linked by sparse passthroughs) over pure late-fusion C3.
- New expert gate ramps from ~0.

**Strategic fork:**
- (a) Over-provision monolithic v1 — right if C3 is 6+ months out.
- (b) Freeze monolithic v1 flat, skip capacity block, build C3 as expansion vehicle — right if C3 is near-term.

## 4 · Fixed-Width Affect Bottleneck

Hundreds of raw affective signals → **permutation-invariant appraisal encoder** (deep-sets / attention pooler over `(key, value)` pairs) → constant N-dim vector. Adding affect source #201 = one new key embedding; no dimension change.

- N=~6–12 recommended (true bottleneck). Avoid N=~100.
- Train encoder once, then freeze.
- Output MUST vary during data collection.
- Wire as modulator, never content peer.
- Anchor a few dims to named axes for interpretability.

## 5 · Biology-Inspired Connectivity Notes

| Regime | Action |
|--------|--------|
| **Neuromodulatory broadcast** | Keep sacred. 1:1 map to NeuroBus. |
| **Wired content connectome** | Honest caveat: 388→40 is narrow by compute budget, not biology. |
| **CLS (hippocampal-cortical)** | Build explicitly: T1 fast → replay → T2 slow. |
| **Topology** | Hub-and-spoke correct. NeuroBus-as-hub. |

---

# Part IX — Council Verdict (2026-06-11)

Council convened on path forward for the NCP brain. Three voices (Skeptic, Pragmatist, Critic) in parallel; four-voice synthesis below.

**Question:** What is the next milestone — monolithic training now, or C3 modular architecture first?

**Verdict: Parallel bootstrap.**

Path C (C3 first) rejected unanimously — too speculative without behavioral data. The real fork was train-before-eval vs eval-before-train. Both have unresolved traps (eval without behavioral variance will be mis-specified; training without a yardstick is blind). The synthesized path:

### Near-term (weeks 1-3)

| Phase | What | Why |
|-------|------|-----|
| **Wk 1** | Build trace logger | JSONL dump of `(input_vec, output, intent, timestamp)` per tick. Shared dependency for both eval and reservoir training. |
| **Wk 2-3** | Reservoir baseline + minimal eval_v0 **simultaneously** | Reservoir provides behavioral variance to validate eval against; eval provides checkpoint promotion signal. They de-risk each other. |

### Medium-term (weeks 4+)

| Phase | What | Why |
|-------|------|-----|
| **Wk 4+** | Evaluate reservoir-vs-BPTT delta | If frozen recurrence + trained readout matches full BPTT, the recurrent core is decorative. If BPTT buys something, C3 becomes the right growth vehicle. |
| **Wk 4+** | Plan C3 architecture | With real loss curves, validated yardstick, and knowledge of whether recurrence matters. Not before. |

### Immediate backlog

- Fix remaining 2 test mock failures (NimMid naming — low priority, cosmetic)
- wirehead detector + vestigiality detector are the first eval_v0 probes (§5.4 of composite-c3-arch.md)

---

# Part VI — Open Questions & Hard Problems

<aside>
⚠️

**Credit assignment across long horizons** — three-factor rules handle short delays (~20 ticks). But if an action today causes a positive outcome in 3 days, the eligibility trace is long dead. Solving this requires the world model (simulate forward) or episodic replay (replay the action during sleep when the outcome is known). Neither is trivial.

</aside>

<aside>
⚠️

**World model accuracy bootstrapping** — the world model trains on hidden state trajectories. But early hidden states (Phase 1) are noisy and untrained. A world model trained on bad trajectories learns bad predictions. Solution: don't train the world model until Phase 2 RL has stabilized the hidden state distribution (~200h). This is why world model is Phase 4, not Phase 2.

</aside>

<aside>
⚠️

**Ariadne ↔ NCP coupling direction** — currently designed as Ariadne feeds NCP (one-way). But ideally the NCP's hidden state should influence where Ariadne looks next (two-way). The two-way coupling requires careful gradient handling to avoid catastrophic interference. Start one-way, add bidirectional in Phase 6.

</aside>

<aside>
⚠️

**Crucible benchmark validity** — Crucible needs benchmark tasks that are stable and representative. If the benchmarks are too easy, Crucible evolves for the benchmark, not reality (Goodhart's law). The benchmark set needs to be curated from real interaction failures — not synthetic tasks.

</aside>

---

# Part VI — Brain Scaling (Net2Net, When to Do It)

See task in Peer Task Queue: **NCP Brain — Scale to 2–5M params (CfC, MoE) before going online.**

**Rule:** Scale happens between Phase 1 and Phase 2 — after imitation learning converges, before RL begins. This ensures:

1. Net2Net expands a *trained* brain (not random noise)
2. RL starts from a richer representation space
3. You never do Net2Net mid-RL (destabilizing)

**The MoE router adds ~1k params and activates 2/8 experts per tick.** This is implemented as a learned gating network on top of the expanded NCP, trained jointly during Phase 2 RL.

---

---

# Part VII — NCP Viability Evidence (Logged 2026-06-11)

Experimental verification of the NCP brain architecture (CfC + NCP wiring, 227k params, 388→40 interface).

| Evidence | Result | What It Proves |
|----------|--------|----------------|
| Temporal integration | **100% accuracy** on 3-tick memory task | CfC recurrence can count across time steps — a stateless MLP cannot |
| Multi-dim output | **R²=0.972** on 40-dim structured target | All output heads receive signal through the NCP wiring |
| Gradient flow | **80.1%** of params (182k/227k) | The 20% without gradient are frozen sparsity masks — all trainable weights are reachable |
| Input sensitivity | Mean abs diff **0.00897** (zeros vs ones) | CfC propagates signal non-trivially even with random weights |
| Urgency gate | **12/12 tests pass** (5 unit, 7 integration) | Full pipeline: NCP output[39] → BUS → dispatcher → eventlog |
| Self-supervised smoothness | ❌ **Collapses to zero** | Temporal smoothness prior alone has trivial solution — needs decoder head or contrastive objective |

**Key open question** (logged to knowledge DB): Can self-supervised sequence pretraining (Track A) warm-start the 40-dim NCP intent space without a separate decoder head? The research page's Stage 0 (I/O contract) is the real blocker — the 40-dim output is a bottleneck that can't reconstruct 388-dim inputs without an auxiliary architecture.

**Next actionable step:** Track C (renderer-as-teacher distillation) once live chat traces accumulate. Requires Stage 0 I/O contract freeze first.

---

## §7.6 — Spec Generator Hardening (2026-06-11)

Review of the spec generator implementation against the §XI contract revealed three classes of fix applied simultaneously:

### Fix A — Thresholds are now baseline-relative (fixes magic constants)

| Spec | Before | After |
|------|--------|-------|
| **threat_urgency** | `monotonic non-decreasing` (brittle; fails on single noise dip) | Spearman ρ(threat, urgency) > 0.8 + top-quartile mean urgency > 0.5. Ordinal, robust. |
| **listens** | `var > 1e-4` (absolute ε, meaningless across training stages) | Variance ratio > 1.5× vs all-constant baseline. Runner computes baseline by running a constant-input batch. |
| **n_tick_memory** | `cos > 0.8` (absolute threshold, no baseline) | Cosine margin > 0.15 above distractor-similarity baseline. Distractor baseline computed per-episode as mean cosine between cue and 32 random distractors. N is swept (1–10), not fixed — the cosine-vs-N curve *is* the A2 credit-horizon measurement. |

### Fix B — SpecReport restructured, no aggregate averaging

**Before:** Single `pass_rate` averaged across specs of wildly different importance. Ablation was a line item in a mean.

**After:**
- `SpecReport.passed` is a per-spec boolean (threshold: 80% for regular specs)
- `Hard gates` (ablation_brain, ablation_zero) are flagged `is_hard_gate=True` and reported separately — never averaged
- Ablation `passed` means *any* detectable signal > 0 pass rate (brain is non-decorative)
- Caller sees per-spec booleans and hard gates as separate categories

### Fix C — Calibration uses correlation, ablation measures eval delta

**calibration:** Predicate is now `Spearman ρ(confidence, correctness) > 0.4`. Confidence = max softmax prob of action logits [0:3]. Correctness = argmax action matches expected action. Hard cases should produce lower confidence — the correlation across difficulty bins is the pass/fail signal.

**ablation:** Delta is measured on the output *behaviorally* — the runner compares ablated (zeroed) vs intact brain output on the same inputs. Not measured against reward. The brain passes if `pass_rate > 0` (any detectable output change).

### Fix D — Air-gap enforced in code, not just in comments

- `EVAL_SEED_NAMESPACE = range(9000, 9999)` — training seeds must never draw from this range
- `SpecGenerator._assert_eval()` raises `ValueError` if an eval-only operation (like `compositional_holdout`) is called with a non-eval seed
- `compositional_holdout()` is a new spec: threat ∧ 3am (high threat during off-hours with conflicting WM). This composition appears in NO training seed's output

### Fix E — Version stamp for regression corpus

`SpecDataset.version` = `md5(f"{seed}:{name}")[:8]`. This freezes the dataset identity:
- Acts as a regression corpus key (§5.2) — datasets with the same version are comparable across runs
- Prevents silent regeneration of held-out sets
- Exposed in `evaluate()` return dict as `"version"`

### Validation requirement

**Every spec must fail on a random-init brain.** If any spec passes before training, that spec is too loose. The first colab run after these changes will validate the floor.

---

## Key Files (When They Exist)

| File | Purpose |
| --- | --- |
| `aegis/brain/ncp.py` | CfC NCP forward pass, hidden state management |
| `aegis/brain/training.py` | Phase 1 imitation + Phase 2 three-factor |
| `aegis/brain/crucible.py` | Genome representation, tournament selection, mutation |
| `aegis/brain/world_model.py` | TinyJEPA predictor, planning loop |
| `aegis/brain/ariadne.py` | Cognitive map, node/edge management |
| `aegis/brain/eligibility.py` | Eligibility trace buffer, deferred weight updates |
| `/var/lib/aegis/ncp_training.jsonl` | Phase 1 training data (cloud responses) |
| `/var/lib/aegis/hidden_states.jsonl` | Phase 4 world model training data |
| `/var/lib/aegis/ariadne_map.db` | SQLite: cognitive map nodes + edges |
| `/var/lib/aegis/crucible_population/` | Genome files for current Crucible population |
| `/opt/aegis/scripts/colab_reservoir.ipynb` | Self-contained Colab notebook for reservoir baseline + eval_v0 on T4 |

---

## X. Reservoir Baseline Experiment (2026-06-11)

Ran on Colab T4 via colab-mcp MCP bridge. 4096 synthetic 388-dim samples, 200 epochs, frozen CfC + trained readout.

### Results

| Metric | Value | Initial Verdict |
|--------|-------|-----------------|
| Reservoir test MSE | 0.055 | ⚠️ Marginal/fail (>0.05) — but untuned |
| BPTT test MSE (50ep) | 0.123 | Undertrained, not comparable |
| eval_v0 probes | 0/0 traces | Synthetic probes buildable without daemon |

### Corrected Interpretation (post-hoc review, 2026-06-11)

**Reservoir: untuned, not negative.** The conclusion "frozen random projections destroy signal" was premature. Echo-state performance is dominated by spectral radius of W_rec (~0.9–1.1), input scaling, readout ridge λ, and CfC-specific τ/dt — none of which were swept. The result says "an untuned random reservoir fails," which was already expected. A sweep (spectral-radius × input-scaling × λ × τ) is the cheap experiment that turns this into a real finding: if even a tuned reservoir can't beat 0.01, that kills the reservoir shortcut (Research Avenue link) for good.

**BPTT: undertrained, not worse.** Comparing a 200-epoch readout-only fit (12.9k params) against 50-epoch full BPTT (227k params) is apples-to-oranges. The honest statement is "BPTT hasn't converged yet." The real comparison is BPTT run to convergence with early-stopping on a val split.

**What the pair does tell you:** Trained recurrence beats random dynamics at this scale — mild evidence that the O(N²) trained core earns its cost (bears on **B3**). And evidence *against* any "freeze the core, only train readouts" shortcut. But it carries a warning: if 227k params need hundreds of epochs on a toy task, learning-from-scratch online at 1 Hz on CPU is hopelessly sample-inefficient. This **reinforces the current path** (pretrain on T4 → freeze → continual-learn online with salience-gated plasticity §6).

**eval_v0 gap:** The synthetic invariant probes (wirehead, vestigiality, calibration) are buildable *without* daemon traces — only the distillation-consistency metric needs real data. Don't let the trace-dependent half stall the buildable half.

**Next moves (all parallel on T4):**
1. Reservoir sweep — spectral radius × input scaling × ridge λ × τ
2. BPTT to convergence — early-stop on val, report epochs-to-best
3. Synthetic eval_v0 probe generator — lights up wirehead + ablation detectors immediately

### Colab MCP Connection Guide (Helios/Linux)

The colab-mcp bridge connects opencode (on a headless GCP VM) to a Colab T4 runtime. The Colab notebook JS connects to a WebSocket server on the VM, forwarded via VS Code SSH tunnel.

**Setup:**
1. opencode.json: `"mcp": {"colab": {"type": "local", "command": ["uvx", "git+https://github.com/googlecolab/colab-mcp", "--ws-port", "34021"], "enabled": true}}`
2. WebSocket server binds to `0.0.0.0:34021` (patched colab-mcp source — default is `127.0.0.1:0`)
3. VS Code Remote SSH auto-detects the port and offers to forward it (`34021 → localhost:34021`)
4. Call `open_colab_browser_connection` — generates URL `https://colab.research.google.com/notebooks/empty.ipynb#mcpProxyToken=TOKEN&mcpProxyPort=34021`
5. Open URL in browser — Colab page JS connects via WebSocket through VS Code tunnel
6. Once connected, notebook tools (`colab_add_code_cell`, `colab_run_code_cell`, etc.) become available

**Known issues:**
- `--pure` flag on `opencode serve` may prevent MCP subprocess from starting (start colab-mcp manually if needed)
- Port changes on each restart unless `--ws-port` is fixed (requires patched `__init__.py`)
- Origin check `allowed_origins = [colab.research.google.com, colab.google.com]` — if VS Code proxy changes origin, patch `websocket_server.py`
- Token logging: patched `session.py` and `websocket_server.py` in uv cache for debugging

---

## XI. The Eval Contract — Replacing the MSE Gate (2026-06-11)

The first experiment's fatal design error: **MSE is the training loss, not the acceptance gate.** They are different objects (§5.1). The pass line should never have been a point-MSE threshold. It should be a battery of behavioral predicates.

### The contract

| Spec | Input construction | Pass predicate | Bears on |
| --- | --- | --- | --- |
| **Threat→urgency** | sweep NeuroBus threat 0→1, hold rest fixed | urgency monotone non-decreasing; >0.5 in top quartile | core reflex |
| **Listens (dead-input)** | vary one input channel only | output variance > ε across channel dims | vestigiality (§2b) |
| **N-tick memory** | cue → N distractor ticks → probe recall | recall correct at horizon N; sweep N | credit horizon (A2/C2) |
| **Calibration** | mixed-difficulty synthetic cases | corr(confidence, correctness) > r | F2 |
| **Ablation** | brain output vs zeroed output | eval delta > 0 | A1 |

### Why MSE is worse than useless as a gate

1. **MSE demands point targets.** "urgency = 0.73" is overfit noise. The daemon needs correct *ordering* — "urgency > 0.5 at high threat." Directional/ordinal predicates are robust.
2. **MSE is dominated by the boring majority.** A model at MSE 0.04 can *fail* threat→urgency by nailing the dense idle ticks and missing rare threat spikes, while a model at 0.055 passes. Same temporal-class-imbalance pathology as §6. **Reservoir-vs-BPTT MSE may rank-invert on behavior.**
3. **The generator that defines the gate is also the pretraining curriculum.** One artifact serves both roles: produce the threat/urgency/memory episodes you train on *and* define the specs you're graded on. Collapses three stalled items into one.

### Air-gap honesty (§5.6)

If you train on the specs, they're no longer held-out. Fix: **disjoint draws from the same generator family.** Train on threat sweeps seeded A, grade on seeds B *and* on compositions never trained together (e.g., threat ∧ 3am). Same generator, separated parameterizations — preserves non-circularity.

### B3 remains open

"Trained recurrence earns its cost" answers a weaker question than B3. The needed ablation: **CfC-with-τ vs equal-param GRU** on the timing-sensitive specs specifically (irregular `dt`, variable inter-event gaps). If the GRU matches, the continuous-time machinery is decorative and B3 flips from "unexploited" to "unjustified."

### Logged next moves

1. Build the spec generator — shared artifact for synthetic Track-C curriculum + behavioral gate
2. CfC-vs-GRU ablation — settles B3
3. Reservoir sweep — spectral radius × input scaling — only if needed (the contract supersedes MSE as the gate, so the sweep is lower priority)
4. BPTT to convergence — early-stop on val, but grade on the behavioral contract, not MSE

**Manual fallback (no VS Code):**
```bash
# Start server manually
COLAB_MCP_PORT=34021 uvx git+https://github.com/googlecolab/colab-mcp --log /tmp/colab-mcp-manual

# Forward port from another terminal
ssh -R 34021:localhost:34021 itznavpreet@<vm-ip>
```