"""Generic PyTorch training template (pre-event boilerplate).

At the event, replace the three TODO parts: `build_data`, `build_model`, `loss_and_metric`.
Everything else (GPU, mixed precision, checkpoints, TensorBoard, early stopping) is done.

    make train                               # or: uv run python -m app.train --epochs 20
    make tb                                  # watch curves at http://localhost:6006
Runs on NVIDIA (CUDA) or LUMI (ROCm); CPU fallback.
"""

import argparse
import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset, random_split
from torch.utils.tensorboard import SummaryWriter


@dataclass
class Config:
    epochs: int = 10
    batch_size: int = 64
    lr: float = 3e-4
    weight_decay: float = 0.01
    val_frac: float = 0.15
    patience: int = 5  # early stopping: epochs without improvement
    seed: int = 42
    workers: int = 2
    run_name: str = ""


def pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")  # NVIDIA *and* AMD/ROCm (LUMI)
    print("WARNING: no GPU found, training on CPU (slow)")
    return torch.device("cpu")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


# ---------------------------------------------------------------- TODO 1: data
def build_data(cfg: Config):
    """Return (train_dataset, val_dataset). Dummy data: 2-class toy problem."""
    x = torch.randn(5000, 32)
    y = (x[:, :4].sum(dim=1) > 0).long()
    ds = TensorDataset(x, y)
    n_val = int(len(ds) * cfg.val_frac)
    return random_split(ds, [len(ds) - n_val, n_val])


# --------------------------------------------------------------- TODO 2: model
def build_model() -> nn.Module:
    """E.g. timm.create_model('efficientnet_b0', pretrained=True, num_classes=N)
    or AutoModelForSequenceClassification.from_pretrained(...)."""
    return nn.Sequential(nn.Linear(32, 128), nn.GELU(), nn.Dropout(0.1), nn.Linear(128, 2))


# ------------------------------------------------------- TODO 3: loss + metric
loss_fn = nn.CrossEntropyLoss()


def loss_and_metric(model: nn.Module, batch, device) -> tuple[torch.Tensor, float]:
    x, y = (t.to(device, non_blocking=True) for t in batch)
    logits = model(x)
    acc = (logits.argmax(1) == y).float().mean().item()
    return loss_fn(logits, y), acc  # metric: higher is better


# ------------------------------------------------------------- training loop
def run_epoch(model, loader, device, opt=None, sched=None, amp_dtype=None):
    train = opt is not None
    model.train(train)
    tot_loss = tot_metric = n = 0
    for batch in loader:
        with (
            torch.set_grad_enabled(train),
            torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None),
        ):
            loss, metric = loss_and_metric(model, batch, device)
        if train:
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
        bs = len(batch[0])
        tot_loss += loss.item() * bs
        tot_metric += metric * bs
        n += bs
    return tot_loss / n, tot_metric / n


def main(cfg: Config) -> None:
    seed_everything(cfg.seed)
    device = pick_device()
    # bf16 mixed precision on modern GPUs (RTX 30xx/40xx, MI250X): ~2x faster, less memory
    amp_dtype = torch.bfloat16 if device.type == "cuda" and torch.cuda.is_bf16_supported() else None
    run = cfg.run_name or time.strftime("%m%d-%H%M%S")
    out = Path("runs") / run
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=2))
    tb = SummaryWriter(out)
    print(f"device={device} amp={amp_dtype} -> {out}")

    train_ds, val_ds = build_data(cfg)
    kw = dict(batch_size=cfg.batch_size, num_workers=cfg.workers, pin_memory=device.type == "cuda")
    train_dl = DataLoader(train_ds, shuffle=True, drop_last=True, **kw)
    val_dl = DataLoader(val_ds, **kw)

    model = build_model().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=cfg.lr, total_steps=cfg.epochs * len(train_dl)
    )

    best, bad = -float("inf"), 0
    for ep in range(1, cfg.epochs + 1):
        t0 = time.time()
        tr_loss, tr_m = run_epoch(model, train_dl, device, opt, sched, amp_dtype)
        va_loss, va_m = run_epoch(model, val_dl, device, amp_dtype=amp_dtype)
        for k, v in dict(loss_train=tr_loss, loss_val=va_loss, m_train=tr_m, m_val=va_m).items():
            tb.add_scalar(k, v, ep)
        flag = ""
        if va_m > best:
            best, bad, flag = va_m, 0, " *best*"
            torch.save(model.state_dict(), out / "best.pt")
        else:
            bad += 1
        print(
            f"ep {ep:3d} | train {tr_loss:.4f}/{tr_m:.4f} | val {va_loss:.4f}/{va_m:.4f}"
            f" | {time.time() - t0:.1f}s{flag}"
        )
        if bad >= cfg.patience:
            print("early stop")
            break
    torch.save(model.state_dict(), out / "last.pt")
    (out / "result.json").write_text(json.dumps({"best_val_metric": best}, indent=2))
    print(f"best val metric {best:.4f} -> {out / 'best.pt'}")


def parse() -> Config:
    p = argparse.ArgumentParser()
    for k, v in asdict(Config()).items():
        p.add_argument(f"--{k.replace('_', '-')}", type=type(v), default=v)
    return Config(**{k.replace("-", "_"): v for k, v in vars(p.parse_args()).items()})


if __name__ == "__main__":
    main(parse())
