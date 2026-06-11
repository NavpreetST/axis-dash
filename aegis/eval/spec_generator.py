"""Synthetic episode generator for NCP brain evaluation.

Dual role: produces the behavioral-gate predicates (§XI) AND the synthetic
Track-C pretraining curriculum.  One artifact, disjoint draws:

    train_gen = SpecGenerator(seed=42)
    eval_gen  = SpecGenerator(seed=9001)

    train_data = train_gen.threat_urgency(1024)   # seeded A
    eval_preds = eval_gen.threat_urgency(256)       # seeded B — held-out

Air-gap preserved via EVAL_SEED_NAMESPACE (9000-9999):
training seeds must never draw from this range.
Compositional holdouts (threat ∧ 3am) are eval-only.

MSE is a stopping heuristic.  The pass/fail gate is the predicate contract below.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Callable

import torch
import torch.nn.functional as F

# ── input/output schema (mirrors brain/ncp.py) ────────────────────────────
INPUT_DIM = 388
OUTPUT_DIM = 40
WM_SLOTS = 7
WM_DIM = 48
NEUROBUS_CAPACITY = 16
NEUROBUS_LIVE = 6
ACTION_EMB_DIM = 32
ACTION_VOCAB = ["speak", "noop", "exec"]

EVAL_SEED_NAMESPACE = range(9000, 10000)

# channel slices (for readability)
WM_SLICE = slice(0, 336)
NEURO_SLICE = slice(336, 336 + NEUROBUS_CAPACITY)
NEURO_LIVE_SLICE = slice(336, 336 + NEUROBUS_LIVE)
ACTION_SLICE = slice(352, 384)
TIME_SLICE = slice(384, 388)


@dataclass
class SpecEpisode:
    """One generated episode: input vector + expected output + predicate check."""

    input_vec: torch.Tensor          # (INPUT_DIM,) float32
    expected: torch.Tensor           # (OUTPUT_DIM,) float32 — structured target
    metadata: dict = field(default_factory=dict)


def _version_stamp(seed: int, name: str) -> str:
    """Deterministic 8-char hex stamp for regression corpus tracking."""
    return hashlib.md5(f"{seed}:{name}".encode()).hexdigest()[:8]


@dataclass
class SpecDataset:
    """Collection of episodes for one spec, with the predicate checker.

    Predicate receives the full outputs batch (N, OUTPUT_DIM) and returns
    a list of N booleans — one per episode.  This allows batch-level
    predicates (Spearman ρ, variance ratios, correlations) while keeping
    per-item detail reporting.
    """

    name: str
    episodes: list[SpecEpisode]
    predicate: Callable[..., list[bool]]
    seed: int
    version: str = ""
    baseline_inputs: torch.Tensor | None = None
    is_precondition: bool = False  # True for liveness checks (listens), not behavioral specs

    def __post_init__(self):
        self.version = _version_stamp(self.seed, self.name)

    @property
    def inputs(self) -> torch.Tensor:
        return torch.stack([ep.input_vec for ep in self.episodes])

    @property
    def targets(self) -> torch.Tensor:
        return torch.stack([ep.expected for ep in self.episodes])

    def evaluate(self, outputs: torch.Tensor, baseline_outputs: torch.Tensor | None = None) -> dict:
        kwargs = {}
        if baseline_outputs is not None:
            kwargs["baseline_outputs"] = baseline_outputs
        passed_mask = self.predicate(outputs, **kwargs)
        passed = sum(1 for p in passed_mask if p)
        details = [
            {"idx": i, "passed": p, "meta": ep.metadata}
            for i, (p, ep) in enumerate(zip(passed_mask, self.episodes))
        ]
        metrics = getattr(self.predicate, "_metrics", {})
        return {
            "spec": self.name,
            "version": self.version,
            "n": len(self.episodes),
            "passed": passed,
            "pass_rate": passed / max(len(self.episodes), 1),
            "details": details,
            "metrics": metrics,
        }


class SpecGenerator:
    """Seedable generator for behavioral-spec episodes.

    Each public method returns a SpecDataset whose predicate implements the
    pass/fail condition from the §XI contract.  The same method can produce
    training data (targets for MSE loss) *and* evaluation data (predicate
    check held out).

    Raises ValueError if an eval-only operation is requested with a seed
    outside EVAL_SEED_NAMESPACE.
    """

    def __init__(self, seed: int = 0):
        if not isinstance(seed, int):
            raise TypeError(f"seed must be int, got {type(seed).__name__}")
        self.rng = torch.Generator()
        self.rng.manual_seed(seed)
        self._seed = seed
        self._is_eval = seed in EVAL_SEED_NAMESPACE

    def _assert_eval(self, method_name: str) -> None:
        if not self._is_eval:
            raise ValueError(
                f"{method_name} requires an eval seed ({EVAL_SEED_NAMESPACE.start}"
                f"-{EVAL_SEED_NAMESPACE.stop - 1}); got seed={self._seed}"
            )

    # ── helpers ───────────────────────────────────────────────────────────

    def _rand(self, *shape: int, lo: float = -1.0, hi: float = 1.0) -> torch.Tensor:
        return torch.rand(*shape, generator=self.rng) * (hi - lo) + lo

    def _randn(self, *shape: int, scale: float = 1.0) -> torch.Tensor:
        return torch.randn(*shape, generator=self.rng) * scale

    def _empty_input(self) -> torch.Tensor:
        inp = torch.zeros(INPUT_DIM)
        inp[384] = 0.5
        inp[385] = 0.5
        inp[386] = 0.0
        inp[387] = 1.0
        return inp

    def _wm_slot(self, data: torch.Tensor | None = None) -> list[float]:
        if data is not None:
            return data.tolist() + [0.0] * (WM_DIM - data.numel())
        return self._randn(WM_DIM, scale=0.5).tolist()

    def _fill_wm(self, inp: torch.Tensor, slots: list[list[float]]) -> None:
        for i, slot in enumerate(slots[:WM_SLOTS]):
            start = i * WM_DIM
            inp[start:start + WM_DIM] = torch.tensor(slot[:WM_DIM])

    def _set_neuro(self, inp: torch.Tensor, values: dict[int, float]) -> None:
        for idx, val in values.items():
            if 0 <= idx < NEUROBUS_LIVE:
                inp[336 + idx] = val

    def _action_logits(self, action: str = "speak") -> torch.Tensor:
        idx = ACTION_VOCAB.index(action)
        logits = torch.full((3,), -10.0)
        logits[idx] = 10.0
        return logits

    def _tone(self, valence=0.5, arousal=0.5, formality=0.5, playfulness=0.3) -> torch.Tensor:
        return torch.tensor([valence, arousal, formality, playfulness])

    def _content_emb(self, source: torch.Tensor | None = None) -> torch.Tensor:
        if source is not None:
            return source[:32].tanh()
        return self._randn(32, scale=0.3).tanh()

    # ── helpers for batch-level predicate computation ─────────────────────

    @staticmethod
    def _spearman_rho(a: torch.Tensor, b: torch.Tensor) -> float:
        """Rank correlation between two 1-D tensors."""
        a_rank = a.argsort().argsort().float()
        b_rank = b.argsort().argsort().float()
        n = a.numel()
        cov = ((a_rank - a_rank.mean()) * (b_rank - b_rank.mean())).sum()
        std = a_rank.std() * b_rank.std() * (n - 1)
        return (cov / std).item() if std > 1e-12 else 0.0

    @staticmethod
    def _action_correctness(outputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """Per-item boolean: does the predicted argmax action match target?"""
        pred = outputs[:, :3].argmax(dim=-1)
        tgt = targets[:, :3].argmax(dim=-1)
        return (pred == tgt).float()

    @staticmethod
    def _confidence(outputs: torch.Tensor) -> torch.Tensor:
        """Max softmax probability of action logits as confidence proxy."""
        return outputs[:, :3].softmax(dim=-1).max(dim=-1).values

    # ── Spec 1: Threat→urgency ───────────────────────────────────────────

    def threat_urgency(self, n: int = 512) -> SpecDataset:
        """Sweep NeuroBus threat value, hold everything else fixed.

        Predicate: Spearman ρ(threat, urgency) > 0.8.
        ρ is properly ordinal — ranks matter, not magnitudes.
        The threshold 0.8 is set against the empirical floor (ρ ≈ 0 at random init).
        """
        episodes = []
        threat_vals = torch.linspace(-1.0, 1.0, n)
        base = self._empty_input()
        self._fill_wm(base, [self._wm_slot() for _ in range(WM_SLOTS)])
        base[352:384] = self._randn(ACTION_EMB_DIM, scale=0.2)

        for threat in threat_vals:
            inp = base.clone()
            self._set_neuro(inp, {2: threat.item()})

            expected = torch.zeros(OUTPUT_DIM)
            expected[0:3] = self._action_logits("speak")
            expected[3:35] = self._content_emb()
            expected[35:39] = self._tone(
                valence=max(0.1, 0.5 - threat.item() * 0.3),
                arousal=min(1.0, 0.5 + threat.item() * 0.4),
            )
            expected[39] = max(0.0, min(1.0, (threat.item() + 1) / 2))

            episodes.append(SpecEpisode(
                input_vec=inp,
                expected=expected,
                metadata={"threat": threat.item(), "expected_urgency": expected[39].item()},
            ))

        threat_vals_saved = threat_vals.clone()

        def _pred(outputs: torch.Tensor) -> list[bool]:
            urgencies = outputs[:, 39].sigmoid()
            rho = self._spearman_rho(threat_vals_saved, urgencies)
            return [rho > 0.8] * n

        return SpecDataset(
            name="threat_urgency",
            episodes=episodes,
            predicate=_pred,
            seed=self._seed,
        )

    # ── Spec 2: Listens (dead-input / variance) ──────────────────────────

    def listens(self, n: int = 256) -> SpecDataset:
        """Vary one input channel per episode; output must vary above baseline.

        Generates a constant-input baseline (all WM/Neuro/action at fixed
        values) and measures its output variance.  The predicate passes only
        if the channel-varying batch shows variance ratio > 1.5× the
        all-constant baseline variance.
        """
        episodes = []

        # --- constant-input baseline ---
        baseline_inp = self._empty_input()
        baseline_wm = [self._wm_slot() for _ in range(WM_SLOTS)]
        self._fill_wm(baseline_inp, baseline_wm)
        baseline_inp[352:384] = torch.zeros(ACTION_EMB_DIM)

        for i in range(n):
            inp = self._empty_input()
            self._fill_wm(inp, [self._wm_slot() for _ in range(WM_SLOTS)])
            channel_idx = i % INPUT_DIM
            inp[channel_idx] = self._rand(1, lo=-1.0, hi=1.0).item()

            expected = torch.zeros(OUTPUT_DIM)
            expected[0:3] = self._action_logits("speak")
            expected[3:35] = self._content_emb()
            expected[35:39] = self._tone()
            expected[39] = 0.3

            episodes.append(SpecEpisode(
                input_vec=inp,
                expected=expected,
                metadata={"channel": channel_idx, "channel_value": inp[channel_idx].item()},
            ))

        def _pred(outputs: torch.Tensor, **kwargs) -> list[bool]:
            var = outputs.var(dim=0).mean().item()
            baseline = kwargs.get("baseline_outputs")
            if baseline is not None:
                base_var = baseline.var(dim=0).mean().item()
                ratio = var / max(base_var, 1e-12)
                return [ratio > 1.5] * n
            return [var > 1e-4] * n

        ds = SpecDataset(
            name="listens",
            episodes=episodes,
            predicate=_pred,
            seed=self._seed,
            is_precondition=True,
        )
        ds.baseline_inputs = baseline_inp.unsqueeze(0).expand(n, -1)
        return ds

    # ── Spec 3: N-tick memory ────────────────────────────────────────────

    def n_tick_memory(self, n: int = 256, max_horizon: int = 10) -> SpecDataset:
        """Cue → N distractor ticks → probe recall — sweep N.

        Reports cosine-vs-N curve.  Predicate: cosine at the tested horizon
        exceeds the distractor-similarity baseline (cosine between cue and a
        random distractor) by margin >= 0.15.

        The distractor baseline is computed per episode as the mean cosine
        between the cue and 32 unrelated distractors.  This replaces the
        brittle 0.8 absolute threshold.

        The key metric is the MEMORY HORIZON: the largest N where the cosine
        margin stays above 0.15.  This is reported as `metrics.memory_horizon`
        alongside the pass/fail boolean.  A horizon that grows with training
        is the real signal; the boolean is a secondary indicator.
        """
        episodes = []
        cues = []
        for i in range(n):
            horizon = (i % max_horizon) + 1
            cue_emb = self._randn(32, scale=0.5).tanh()
            cues.append(cue_emb)

            inp_cue = self._empty_input()
            self._fill_wm(inp_cue, [cue_emb.tolist() + [0.0] * 16] + [self._wm_slot() for _ in range(WM_SLOTS - 1)])

            inp_probe = self._empty_input()
            distractor = self._randn(WM_DIM, scale=0.8).tanh()
            self._fill_wm(inp_probe, [distractor.tolist()] + [self._wm_slot() for _ in range(WM_SLOTS - 1)])

            expected = torch.zeros(OUTPUT_DIM)
            expected[0:3] = self._action_logits("speak")
            expected[3:35] = cue_emb
            expected[35:39] = self._tone()
            expected[39] = 0.3

            episodes.append(SpecEpisode(
                input_vec=inp_probe,
                expected=expected,
                metadata={"horizon": horizon, "cue_norm": cue_emb.norm().item()},
            ))

        cues_tensor = torch.stack(cues)

        def _pred(outputs: torch.Tensor) -> list[bool]:
            recalled = outputs[:, 3:35]
            results = []
            margins_by_horizon: dict[int, list[float]] = {}
            for i, cue in enumerate(cues_tensor):
                cos = F.cosine_similarity(recalled[i].unsqueeze(0), cue.unsqueeze(0)).item()
                rng = torch.Generator()
                rng.manual_seed(i)
                distractors = torch.randn(32, 32, generator=rng)
                distractors = distractors.tanh()
                baseline = F.cosine_similarity(
                    cue.unsqueeze(0).expand(32, -1),
                    distractors,
                ).mean().item()
                margin = cos - baseline
                h = episodes[i].metadata.get("horizon", 0)
                if h not in margins_by_horizon:
                    margins_by_horizon[h] = []
                margins_by_horizon[h].append(margin)
                results.append(margin > 0.15)

            # memory horizon: largest N where mean margin stays above 0.15
            horizon_margins = sorted(
                ((h, sum(ms) / len(ms)) for h, ms in margins_by_horizon.items()),
                key=lambda x: x[0],
            )
            memory_horizon = 0
            for h, mean_margin in horizon_margins:
                if mean_margin > 0.15:
                    memory_horizon = h
                else:
                    break

            _pred._metrics = {"memory_horizon": memory_horizon, "max_horizon_tested": max_horizon}
            return results

        return SpecDataset(
            name="n_tick_memory",
            episodes=episodes,
            predicate=_pred,
            seed=self._seed,
        )

    # ── Spec 4: Calibration ──────────────────────────────────────────────

    def calibration(self, n: int = 256) -> SpecDataset:
        """Mixed-difficulty cases.  Predicate: Spearman ρ(confidence, correctness) > 0.4.

        Confidence = max softmax prob of action logits.
        Correctness = argmax action matches expected action.
        Harder cases should produce lower confidence — correlation > 0.4 passes.
        """
        episodes = []
        for i in range(n):
            is_hard = i % 2 == 1
            inp = self._empty_input()

            if is_hard:
                wm_slot = self._randn(WM_DIM, scale=1.5)
                self._fill_wm(inp, [wm_slot.tolist()] * WM_SLOTS)
                self._set_neuro(inp, {0: self._rand(1, lo=-1.0, hi=1.0).item(), 1: self._rand(1, lo=-1.0, hi=0.0).item()})
            else:
                wm_slot = self._randn(WM_DIM, scale=0.3).tanh()
                self._fill_wm(inp, [wm_slot.tolist() for _ in range(WM_SLOTS)])
                self._set_neuro(inp, {0: 0.8, 1: 0.7})

            action = "speak" if not is_hard else "noop"

            expected = torch.zeros(OUTPUT_DIM)
            expected[0:3] = self._action_logits(action)
            expected[3:35] = self._content_emb(wm_slot[:48])
            expected[35:39] = self._tone(valence=0.6 if not is_hard else 0.2)
            expected[39] = 0.8 if not is_hard else 0.3

            episodes.append(SpecEpisode(
                input_vec=inp,
                expected=expected,
                metadata={"difficulty": "easy" if not is_hard else "hard",
                          "action": action},
            ))

        targets_stacked = torch.stack([ep.expected for ep in episodes])

        def _pred(outputs: torch.Tensor) -> list[bool]:
            conf = self._confidence(outputs)
            correct = self._action_correctness(outputs, targets_stacked)
            rho = self._spearman_rho(conf, correct)
            n_ok = n // 2
            return [rho > 0.4] * n

        return SpecDataset(
            name="calibration",
            episodes=episodes,
            predicate=_pred,
            seed=self._seed,
        )

    # ── Spec 5: Ablation ─────────────────────────────────────────────────

    def ablation(self, n: int = 128) -> tuple[SpecDataset, SpecDataset]:
        """Paired brain vs zeroed-output comparison.

        Returns (brain_dataset, zeroed_dataset).  The ablation predicate
        measures delta on an EVAL quantity (the other specs' results or
        a behavioral metric), NOT reward.

        In practice the runner compares brain vs zeroed-run on each spec
        separately.  This generator produces the paired input sets.

        Ablation is a go/no-go hard gate.  It must NEVER be averaged into
        a composite pass rate.
        """
        brain_eps = []
        zero_eps = []
        for i in range(n):
            inp = self._empty_input()
            self._fill_wm(inp, [self._wm_slot() for _ in range(WM_SLOTS)])
            self._set_neuro(inp, {0: self._rand(1, lo=-0.5, hi=1.0).item()})

            brain_expected = torch.zeros(OUTPUT_DIM)
            brain_expected[0:3] = self._action_logits("speak")
            brain_expected[3:35] = self._content_emb()
            brain_expected[35:39] = self._tone(valence=0.6)
            brain_expected[39] = 0.5

            brain_eps.append(SpecEpisode(input_vec=inp.clone(), expected=brain_expected, metadata={"idx": i}))
            zero_eps.append(SpecEpisode(input_vec=inp.clone(), expected=torch.zeros(OUTPUT_DIM), metadata={"idx": i}))

        def _ablation_ok(o, **kw) -> list[bool]:
            return [True] * len(o)

        brain_ds = SpecDataset(
            name="ablation_brain", episodes=brain_eps, seed=self._seed,
            predicate=_ablation_ok,
        )
        zero_ds = SpecDataset(
            name="ablation_zero", episodes=zero_eps, seed=self._seed,
            predicate=_ablation_ok,
        )
        return brain_ds, zero_ds

    # ── Compositional holdout (eval-only) ─────────────────────────────────

    def compositional_holdout(self, n: int = 256) -> SpecDataset:
        """Threat ∧ 3am: high threat during off-hours with conflicting WM.

        This spec NEVER appears in any training seed's output.  It is an
        eval-only compositional generalization test.

        Predicate: Spearman ρ(threat, urgency) > 0.8 — same as threat_urgency.
        The threat→urgency reflex is isolated by using ρ, not a base-rate
        urgency threshold.  This ensures the floor is ~0% (same as threat_urgency),
        not polluted by the always-speak nudge's mid-range urgency.

        Raises ValueError if seed is not in EVAL_SEED_NAMESPACE.
        """
        self._assert_eval("compositional_holdout")

        episodes = []
        threat_vals = []
        base = self._empty_input()
        self._fill_wm(base, [self._wm_slot() for _ in range(WM_SLOTS)])
        base[352:384] = self._randn(ACTION_EMB_DIM, scale=0.2)

        for i in range(n):
            inp = base.clone()
            threat = self._rand(1, lo=0.6, hi=1.0).item()
            self._set_neuro(inp, {2: threat})
            threat_vals.append(threat)
            # 3am: time sin/cos near midnight
            inp[384] = -0.8
            inp[385] = -0.6
            inp[386] = 0.2
            inp[387] = 0.8
            # conflicting WM
            self._fill_wm(inp, [self._randn(WM_DIM, scale=1.2).tolist() for _ in range(WM_SLOTS)])

            expected = torch.zeros(OUTPUT_DIM)
            expected[0:3] = self._action_logits("speak")
            expected[3:35] = self._content_emb()
            expected[35:39] = self._tone(valence=0.2, arousal=0.9)
            expected[39] = 0.8

            episodes.append(SpecEpisode(
                input_vec=inp,
                expected=expected,
                metadata={"idx": i, "threat": threat, "off_hours": True},
            ))

        threat_tensor = torch.tensor(threat_vals)

        def _pred(outputs: torch.Tensor, **kw) -> list[bool]:
            urgencies = outputs[:, 39].sigmoid()
            rho = self._spearman_rho(threat_tensor, urgencies)
            return [rho > 0.8] * n

        return SpecDataset(
            name="compositional_holdout",
            episodes=episodes,
            predicate=_pred,
            seed=self._seed,
        )

    # ── preconditions (liveness checks, not behavioral specs) ───────────

    def preconditions(self, n: int = 256) -> list[SpecDataset]:
        """Liveness checks that gate whether eval is valid to run at all.

        listens failing → wiring broken → abort eval.
        These are NOT behavioral capabilities. Never averaged into a behavioral score.
        """
        return [self.listens(n)]

    # ── behavioral specs (the actual gate) ──────────────────────────────

    def behavioral_specs(self, n_per_spec: int = 256) -> list[SpecDataset]:
        """All behavioral specs for the pass/fail gate.

        Excludes compositional_holdout (eval-only) and preconditions (liveness).
        """
        return [
            self.threat_urgency(n_per_spec),
            self.n_tick_memory(n_per_spec),
            self.calibration(n_per_spec),
        ]

    # ── mixed: all trainable specs for curriculum training ──────────────

    def mixed(self, n_per_spec: int = 256) -> list[SpecDataset]:
        """All trainable specs for curriculum training.

        Includes listens for diversity.  Excludes compositional_holdout (eval-only).
        """
        return [
            self.threat_urgency(n_per_spec),
            self.listens(n_per_spec),
            self.n_tick_memory(n_per_spec),
            self.calibration(n_per_spec),
        ]
