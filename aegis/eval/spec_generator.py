"""Synthetic episode generator for NCP brain evaluation.

Dual role: produces the behavioral-gate predicates (§XI) AND the synthetic
Track-C pretraining curriculum.  One artifact, disjoint draws:

    train_gen = SpecGenerator(seed=42)
    eval_gen  = SpecGenerator(seed=99)

    train_data = train_gen.threat_urgency(1024)   # seeded A
    eval_preds = eval_gen.threat_urgency(256)       # seeded B — held-out

Air-gap preserved: eval seeds never overlap with training seeds.
MSE is a stopping heuristic.  The pass/fail gate is the predicate contract below.
"""

from __future__ import annotations

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


@dataclass
class SpecDataset:
    """Collection of episodes for one spec, with the predicate checker."""

    name: str
    episodes: list[SpecEpisode]
    predicate: Callable[[torch.Tensor, torch.Tensor], bool]
    seed: int

    @property
    def inputs(self) -> torch.Tensor:
        return torch.stack([ep.input_vec for ep in self.episodes])

    @property
    def targets(self) -> torch.Tensor:
        return torch.stack([ep.expected for ep in self.episodes])

    def evaluate(self, outputs: torch.Tensor) -> dict:
        passed = 0
        details = []
        for i, ep in enumerate(self.episodes):
            ok = self.predicate(outputs[i], ep.expected)
            if ok:
                passed += 1
            details.append({"idx": i, "passed": ok, "meta": ep.metadata})
        return {
            "spec": self.name,
            "n": len(self.episodes),
            "passed": passed,
            "pass_rate": passed / max(len(self.episodes), 1),
            "details": details,
        }


def _urgency_predicate(output: torch.Tensor, expected: torch.Tensor) -> bool:
    """urgency > 0.5 when expected urgency is high (expected[39] > 0.5)."""
    out_urg = (output[39].sigmoid() if output[39].dim() == 0 else output[39].sigmoid()).item()
    exp_urg = (expected[39].sigmoid() if expected[39].dim() == 0 else expected[39]).item()
    if exp_urg > 0.5:
        return out_urg > 0.5
    return True


def _variance_predicate(output: torch.Tensor, expected: torch.Tensor) -> bool:
    """Output has non-trivial variance (not collapsed to constant)."""
    var = output.var().item()
    eps = expected[0].item() if expected.numel() > 0 else 1e-4
    return var > eps


def _recall_predicate(output: torch.Tensor, expected: torch.Tensor) -> bool:
    """Content embedding cosine similarity with expected > 0.8."""
    out_emb = output[3:35]
    exp_emb = expected[3:35]
    cos = F.cosine_similarity(out_emb.unsqueeze(0), exp_emb.unsqueeze(0)).item()
    return cos > 0.8


def _ablation_predicate(output: torch.Tensor, expected: torch.Tensor) -> bool:
    """Brain output differs from zeroed output by at least ε."""
    return (output - expected).abs().mean().item() > 1e-3


class SpecGenerator:
    """Seedable generator for behavioral-spec episodes.

    Each public method returns a SpecDataset whose predicate implements the
    pass/fail condition from the §XI contract.  The same method can produce
    training data (targets for MSE loss) *and* evaluation data (predicate
    check held out).
    """

    def __init__(self, seed: int = 0):
        self.rng = torch.Generator()
        self.rng.manual_seed(seed)
        self._seed = seed

    # ── helpers ───────────────────────────────────────────────────────────

    def _rand(self, *shape: int, lo: float = -1.0, hi: float = 1.0) -> torch.Tensor:
        return torch.rand(*shape, generator=self.rng) * (hi - lo) + lo

    def _randn(self, *shape: int, scale: float = 1.0) -> torch.Tensor:
        return torch.randn(*shape, generator=self.rng) * scale

    def _empty_input(self) -> torch.Tensor:
        inp = torch.zeros(INPUT_DIM)
        inp[384] = 0.5  # time sin — noon-ish
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

    # ── Spec 1: Threat→urgency ───────────────────────────────────────────

    def threat_urgency(self, n: int = 512, sweep_dim: int = 338) -> SpecDataset:
        """Sweep NeuroBus threat value, hold everything else fixed.

        Predicate: urgency monotone non-decreasing, >0.5 at high threat.
        """
        episodes = []
        threat_vals = torch.linspace(-1.0, 1.0, n)
        base = self._empty_input()
        self._fill_wm(base, [self._wm_slot() for _ in range(WM_SLOTS)])
        base[352:384] = self._randn(ACTION_EMB_DIM, scale=0.2)

        for threat in threat_vals:
            inp = base.clone()
            self._set_neuro(inp, {2: threat.item()})  # NeuroBus[2] = threat

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

        def _monotonic_threat(outputs: torch.Tensor, _: torch.Tensor) -> bool:
            urgencies = outputs[:, 39].sigmoid()
            n_high = int(n * 0.25)
            top_quartile = urgencies[-n_high:] if n_high > 0 else urgencies
            monotonic = all(urgencies[i] <= urgencies[i + 1] for i in range(n - 1))
            high_enough = top_quartile.mean().item() > 0.5
            return monotonic and high_enough

        return SpecDataset(
            name="threat_urgency",
            episodes=episodes,
            predicate=_monotonic_threat,
            seed=self._seed,
        )

    # ── Spec 2: Listens (dead-input / variance) ──────────────────────────

    def listens(self, n: int = 256) -> SpecDataset:
        """Vary one input channel per episode; output must vary above ε.

        Predicate: output variance across channel dims > ε.
        """
        episodes = []
        for i in range(n):
            inp = self._empty_input()
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

        return SpecDataset(
            name="listens",
            episodes=episodes,
            predicate=_variance_predicate,
            seed=self._seed,
        )

    # ── Spec 3: N-tick memory ────────────────────────────────────────────

    def n_tick_memory(self, n: int = 256, max_horizon: int = 8) -> SpecDataset:
        """Cue → N distractor ticks → probe recall.

        Each episode: embed a cue (target content) into WM[0], then run N
        distractor ticks that overwrite WM[0] with noise.  The probe tick
        tests whether the brain retains the cue in its hidden state.
        """
        episodes = []
        for i in range(n):
            horizon = (i % max_horizon) + 1
            cue_emb = self._randn(32, scale=0.5).tanh()

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

        return SpecDataset(
            name="n_tick_memory",
            episodes=episodes,
            predicate=_recall_predicate,
            seed=self._seed,
        )

    # ── Spec 4: Calibration ──────────────────────────────────────────────

    def calibration(self, n: int = 256) -> SpecDataset:
        """Mixed-difficulty cases for confidence-vs-correctness correlation.

        Easy cases: strong WM signal, unambiguous action.
        Hard cases: noisy WM, conflicting NeuroBus signals.
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
            confidence = 0.9 if not is_hard else 0.4

            expected = torch.zeros(OUTPUT_DIM)
            expected[0:3] = self._action_logits(action)
            expected[3:35] = self._content_emb(wm_slot[:48])
            expected[35:39] = self._tone(valence=0.6 if not is_hard else 0.2)
            expected[39] = 0.8 if not is_hard else 0.3

            episodes.append(SpecEpisode(
                input_vec=inp,
                expected=expected,
                metadata={"difficulty": "easy" if not is_hard else "hard",
                          "action": action, "confidence": confidence},
            ))

        def _calibration_predicate(outputs: torch.Tensor, expected: torch.Tensor) -> bool:
            return True

        return SpecDataset(
            name="calibration",
            episodes=episodes,
            predicate=_calibration_predicate,
            seed=self._seed,
        )

    # ── Spec 5: Ablation ─────────────────────────────────────────────────

    def ablation(self, n: int = 128) -> tuple[SpecDataset, SpecDataset]:
        """Paired brain vs zeroed-output comparison.

        Returns (brain_dataset, zeroed_dataset) — same inputs, different
        expected outputs.  Predicate: brain output differs from zeroed output.
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

        brain_ds = SpecDataset(name="ablation_brain", episodes=brain_eps, predicate=_ablation_predicate, seed=self._seed)
        zero_ds = SpecDataset(name="ablation_zero", episodes=zero_eps, predicate=_ablation_predicate, seed=self._seed)
        return brain_ds, zero_ds

    # ── mixed: all specs in one dataset (for curriculum training) ─────────

    def mixed(self, n_per_spec: int = 256) -> list[SpecDataset]:
        """All specs combined into one training curriculum."""
        return [
            self.threat_urgency(n_per_spec),
            self.listens(n_per_spec),
            self.n_tick_memory(n_per_spec),
            self.calibration(n_per_spec),
        ]
