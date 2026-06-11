"""Reservoir baseline harness for the NCP brain.

Freezes the CfC recurrent core (227k params), trains only a lightweight
readout on top of the 160-dim hidden state. Establishes the cost floor:
how well does a frozen random core + trained readout perform vs full BPTT?

Usage:
    python -m aegis.brain.reservoir          # run with synthetic data
    python -m aegis.brain.reservoir --real    # run with real trace data
"""
from __future__ import annotations

import argparse
import logging
import math
import time

import torch
import torch.nn as nn
import torch.nn.functional as F

from aegis.brain.ncp import BRAIN, INPUT_DIM, OUTPUT_DIM, NEUROBUS_LIVE, NEUROBUS_CAPACITY

log = logging.getLogger("brain.reservoir")

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

HIDDEN_DIM = 160  # CfC hidden state: 80 inter + 40 command + 40 motor


class Readout(nn.Module):
    """Trainable readout from frozen reservoir state (160 → 40)."""

    def __init__(self, hidden_dim: int = HIDDEN_DIM, output_dim: int = OUTPUT_DIM):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.Tanh(),
            nn.Linear(64, output_dim),
        )

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        return self.net(h)


def freeze_ncp() -> None:
    for p in BRAIN.parameters():
        p.requires_grad_(False)
    BRAIN.eval()
    log.info("frozen %d NCP params", sum(p.numel() for p in BRAIN.parameters()))


# ── synthetic data ──────────────────────────────────────────────────────────

def _make_synthetic_target(input_vec: torch.Tensor) -> torch.Tensor:
    """Create a structured 40-dim target from the 388-dim input.

    The target uses three signals from the input:
      - The first 48-dim WM slot (MiniLM embedding region) → content_emb [3:35]
      - NeuroBus reward [336] → valence [35]
      - NeuroBus novelty [337] → arousal [36]
      - A binary threshold on WM activity → urgency [39]
    Plus noise to avoid trivial interpolation.
    """
    target = torch.zeros(OUTPUT_DIM, device=input_vec.device)
    wm_slot_0 = input_vec[0:48]
    target[3:35] = wm_slot_0[0:32].tanh()
    reward = input_vec[336] if NEUROBUS_LIVE > 0 else 0.0
    novelty = input_vec[337] if NEUROBUS_LIVE > 1 else 0.0
    target[35] = reward * 0.5 + 0.5
    target[36] = novelty * 0.5 + 0.5
    target[37] = 0.5
    target[38] = 0.3
    wm_energy = input_vec[0:48].abs().mean()
    target[39] = (wm_energy > 0.1).float()
    target[0:3] = F.softmax(torch.tensor([1.0, 0.0, 0.0]), dim=0)
    return target + torch.randn(OUTPUT_DIM, device=input_vec.device) * 0.01


def synthetic_dataset(
    n_samples: int = 4096,
    seq_len: int = 5,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Generate synthetic (inputs, targets, hidden_states) triple.

    Each sample is a sequence of `seq_len` ticks. The hidden state from the
    frozen NCP is collected after processing the sequence.
    """
    freeze_ncp()
    all_h = []
    all_targets = []
    all_inputs = []

    with torch.no_grad():
        for _ in range(n_samples):
            BRAIN.hx = None
            hx = None
            for t in range(seq_len):
                inp = torch.randn(INPUT_DIM, device=DEVICE) * 0.3
                inp[336:336 + NEUROBUS_LIVE] = torch.randn(NEUROBUS_LIVE, device=DEVICE) * 0.2
                target = _make_synthetic_target(inp)
                _, hx = BRAIN.rnn(inp.view(1, 1, -1), hx)
            all_h.append(hx.squeeze())
            all_targets.append(target)
            all_inputs.append(inp)

    return (
        torch.stack(all_h),
        torch.stack(all_targets),
        torch.stack(all_inputs),
    )


# ── training ────────────────────────────────────────────────────────────────

def train_readout(
    readout: Readout,
    h: torch.Tensor,
    targets: torch.Tensor,
    epochs: int = 200,
    lr: float = 1e-3,
) -> list[float]:
    opt = torch.optim.AdamW(readout.parameters(), lr=lr)
    losses = []
    for ep in range(epochs):
        opt.zero_grad()
        pred = readout(h)
        loss = F.mse_loss(pred, targets)
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(readout.parameters(), 1.0)
        opt.step()
        losses.append(loss.item())
        if ep % 40 == 0 or ep == epochs - 1:
            log.info("  epoch %3d — loss %.6f — grad_norm %.4f", ep, loss.item(), grad_norm)
    return losses


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Reservoir baseline for NCP brain")
    parser.add_argument("--samples", type=int, default=4096, help="number of synthetic sequences")
    parser.add_argument("--seq-len", type=int, default=5, help="ticks per sequence")
    parser.add_argument("--epochs", type=int, default=200, help="readout training epochs")
    parser.add_argument("--lr", type=float, default=1e-3, help="learning rate")
    args = parser.parse_args()

    log.info("reservoir baseline — %s samples × %d ticks", args.samples, args.seq_len)
    log.info("device: %s", DEVICE)
    t0 = time.time()

    h, targets, _ = synthetic_dataset(args.samples, args.seq_len)
    log.info("data generated — h.shape=%s, targets.shape=%s — %.2fs", h.shape, targets.shape, time.time() - t0)

    train_h, train_t = h[:args.samples // 2], targets[:args.samples // 2]
    test_h, test_t = h[args.samples // 2:], targets[args.samples // 2:]

    readout = Readout().to(DEVICE)
    n_readout = sum(p.numel() for p in readout.parameters())
    log.info("readout params: %d", n_readout)

    t0 = time.time()
    losses = train_readout(readout, train_h, train_t, epochs=args.epochs, lr=args.lr)
    train_time = time.time() - t0

    with torch.no_grad():
        train_pred = readout(train_h)
        test_pred = readout(test_h)
        train_loss = F.mse_loss(train_pred, train_t).item()
        test_loss = F.mse_loss(test_pred, test_t).item()

    log.info("")
    log.info("═" * 50)
    log.info("reservoir baseline results")
    log.info("═" * 50)
    log.info("  train MSE:  %.6f", train_loss)
    log.info("  test MSE:   %.6f", test_loss)
    log.info("  final train loss: %.6f (epoch %d)", losses[-1], args.epochs)
    log.info("  train time: %.2fs", train_time)
    log.info("  readout params: %d", n_readout)
    log.info("  frozen NCP params: %d", sum(p.numel() for p in BRAIN.parameters()))
    log.info("═" * 50)

    if test_loss < 0.01:
        log.info("  ✅ BASELINE PASS — readout can learn from frozen reservoir")
    else:
        log.info("  ⚠️  BASELINE MARGINAL — readout may need more capacity or epochs")
    log.info("")

    return {
        "train_loss": train_loss,
        "test_loss": test_loss,
        "n_readout": n_readout,
        "n_frozen": sum(p.numel() for p in BRAIN.parameters()),
    }


if __name__ == "__main__":
    main()
