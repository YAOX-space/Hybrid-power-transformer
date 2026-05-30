"""
msffn_fault_detector.py  —  Multi-Scale Feature Fusion Network (MSFFN)
=======================================================================
Three-branch architecture for HPT fault detection.

  Branch A  statistical  : 9 statistics × 9 channels = 81-dim  → MLP(81→256→128)
  Branch B  frequency    : FFT bins 1-26 × 9 channels = 234-dim → MLP(234→256→128)
  Branch C  temporal TCN : causal dilated conv [32,64,128], dilation 1/2/4
                           → GlobalAvgPool → Linear(128)
  Fusion  : gated attention over 3 branches → weighted sum (128-dim)
  Head    : Linear(128→64→7)

Key design choices
------------------
  Branches A and B are *deterministic transforms* — they give the network
  direct access to the same statistical/frequency features that let Random
  Forest succeed on small datasets.  Branch C retains causal temporal
  modelling for transient fault onset.  Total parameters ~340 K vs TCN ~800 K,
  reducing overfitting on 1 050-file datasets.

Usage
-----
  python msffn_fault_detector.py --train [--device auto]
  python msffn_fault_detector.py --eval  [--device auto]
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Tuple

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from torch.optim import Adam
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import Dataset

from data_loader import (
    FAULT_CLASSES, N_CLASSES, N_FEAT_FAULT, RAW_DIR, WINDOW_SIZE,
    build_fault_dataset, make_balanced_loader, make_val_loader,
    _feat_ver as _FEAT_VER,
)

# ── Paths ──────────────────────────────────────────────────────────────────────
MODEL_DIR = Path(__file__).resolve().parent.parent / 'data' / 'models'
MODEL_DIR.mkdir(exist_ok=True)
# Checkpoint path includes feature version so v1 and v2 models coexist
CKPT_PATH = MODEL_DIR / f'msffn_fault_detector_{RAW_DIR.name}_v{_FEAT_VER}.pt'

# ── Hyper-parameters ───────────────────────────────────────────────────────────
BATCH_SIZE   = 256
LR           = 1e-3
EPOCHS       = 80
PATIENCE     = 12
NOISE_STD    = 0.02
SCALE_RANGE  = (0.90, 1.10)
JITTER_MAX   = 2

BRANCH_DIM   = 128
TCN_CHANNELS = [32, 64, 128]
N_FFT_BINS   = 26          # bins 1–26  ≈  200 Hz – 5 200 Hz  (at 20 kHz, 5 ms window)
N_STAT_FEATS = 9 * N_FEAT_FAULT   # 81 (v1) or 126 (v2 with 14 channels)
N_FFT_FEATS  = N_FFT_BINS * N_FEAT_FAULT  # 234 (v1) or 364 (v2)


# ── Deterministic feature extractors ──────────────────────────────────────────

def stat_features(x: torch.Tensor) -> torch.Tensor:
    """Return 81-dim statistical feature vector from (B, T, C) window.

    Matches the feature set used by the winning Random Forest baseline so that
    Branch A gives the network the same discriminative signal.

    Computed on CPU because DirectML does not support aten::std.correction
    and falls back to CPU anyway, causing allocator fragmentation over many
    epochs. Explicit CPU avoids that leak.
    """
    device = x.device
    x = x.cpu()
    dx = x[:, 1:, :] - x[:, :-1, :]
    out = torch.cat([
        x.mean(dim=1),
        x.std(dim=1, unbiased=False),
        x.pow(2).mean(dim=1).sqrt(),      # RMS
        x.amin(dim=1),
        x.amax(dim=1),
        x.amax(dim=1) - x.amin(dim=1),   # peak-to-peak
        x[:, -1, :] - x[:, 0, :],        # trend
        dx.abs().mean(dim=1),
        dx.abs().amax(dim=1),
    ], dim=1)   # (B, 81)
    return out.to(device)


def fft_features(x: torch.Tensor) -> torch.Tensor:
    """Return 234-dim FFT magnitude feature vector from (B, T, C) window.

    FFT is forced to CPU because DirectML (Windows GPU) does not support
    complex-valued operations (rfft produces ComplexFloat internally).
    """
    mag = torch.fft.rfft(x.cpu(), dim=1).abs()    # (B, 51, C)  — CPU always
    return mag[:, 1:N_FFT_BINS + 1, :].reshape(x.shape[0], -1).to(x.device)  # (B, 234)


# ── Network modules ────────────────────────────────────────────────────────────

def _mlp(in_dim: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(in_dim, 256), nn.BatchNorm1d(256), nn.GELU(), nn.Dropout(0.2),
        nn.Linear(256, BRANCH_DIM), nn.BatchNorm1d(BRANCH_DIM), nn.GELU(),
    )


class _CausalConv1d(nn.Module):
    def __init__(self, in_c: int, out_c: int, kernel: int = 3, dilation: int = 1):
        super().__init__()
        pad = (kernel - 1) * dilation
        self.conv = nn.Conv1d(in_c, out_c, kernel, dilation=dilation, padding=pad)
        self._trim = pad

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.conv(x)
        return out[:, :, :-self._trim] if self._trim > 0 else out


class _ResBlock(nn.Module):
    def __init__(self, ch: int, dilation: int):
        super().__init__()
        self.block = nn.Sequential(
            _CausalConv1d(ch, ch, dilation=dilation),
            nn.BatchNorm1d(ch), nn.GELU(),
            _CausalConv1d(ch, ch, dilation=dilation),
            nn.BatchNorm1d(ch),
        )
        self.act = nn.GELU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.act(x + self.block(x))


class _LightTCN(nn.Module):
    def __init__(self):
        super().__init__()
        in_c = N_FEAT_FAULT
        layers: list[nn.Module] = []
        for i, out_c in enumerate(TCN_CHANNELS):
            layers += [nn.Conv1d(in_c, out_c, 1), nn.BatchNorm1d(out_c), nn.GELU(),
                       _ResBlock(out_c, dilation=2 ** i)]
            in_c = out_c
        self.net  = nn.Sequential(*layers)
        self.pool = nn.AdaptiveAvgPool1d(1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.pool(self.net(x.permute(0, 2, 1))).squeeze(-1)   # (B, 128)


class MSFFN(nn.Module):
    """Multi-Scale Feature Fusion Network for 7-class HPT fault detection."""

    def __init__(self, n_classes: int = N_CLASSES):
        super().__init__()
        self.stat_mlp = _mlp(N_STAT_FEATS)
        self.fft_mlp  = _mlp(N_FFT_FEATS)
        self.tcn      = _LightTCN()
        self.tcn_proj = nn.Linear(TCN_CHANNELS[-1], BRANCH_DIM)

        self.gate = nn.Sequential(
            nn.Linear(BRANCH_DIM * 3, 64), nn.GELU(),
            nn.Linear(64, 3), nn.Softmax(dim=-1),
        )
        self.head = nn.Sequential(
            nn.Linear(BRANCH_DIM, 64), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(64, n_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a = self.stat_mlp(stat_features(x))
        b = self.fft_mlp(fft_features(x))
        c = self.tcn_proj(self.tcn(x))
        w = self.gate(torch.cat([a, b, c], dim=1))          # (B, 3)
        fused = w[:, 0:1] * a + w[:, 1:2] * b + w[:, 2:3] * c
        return self.head(fused)

    def branch_weights(self, x: torch.Tensor) -> torch.Tensor:
        """Return per-sample gate weights (B, 3) for interpretability."""
        with torch.no_grad():
            a = self.stat_mlp(stat_features(x))
            b = self.fft_mlp(fft_features(x))
            c = self.tcn_proj(self.tcn(x))
            return self.gate(torch.cat([a, b, c], dim=1))


# ── Data augmentation ──────────────────────────────────────────────────────────

class _AugDataset(Dataset):
    def __init__(self, base: Dataset, augment: bool = True):
        self.base    = base
        self.augment = augment

    def __len__(self) -> int:
        return len(self.base)

    @property
    def y(self):
        return self.base.y

    def __getitem__(self, idx: int):
        x, y = self.base[idx]
        if self.augment:
            x = x + torch.randn_like(x) * NOISE_STD
            scale = SCALE_RANGE[0] + torch.rand(1).item() * (SCALE_RANGE[1] - SCALE_RANGE[0])
            x = x * scale
            shift = torch.randint(-JITTER_MAX, JITTER_MAX + 1, (1,)).item()
            if shift > 0:
                x = torch.cat([x[shift:], x[-shift:]], dim=0)
            elif shift < 0:
                x = torch.cat([x[shift:], x[:shift]], dim=0)
        return x, y


# ── Device resolution ──────────────────────────────────────────────────────────

def resolve_device(device: str) -> Tuple[torch.device, str, bool]:
    if device == 'auto':
        if torch.cuda.is_available():
            device = 'cuda'
        else:
            try:
                import torch_directml
                return torch_directml.device(), 'dml', False
            except Exception:
                device = 'cpu'
    if device == 'cuda':
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA requested but not available')
        torch.backends.cudnn.benchmark = True
        return torch.device('cuda'), 'cuda', True
    return torch.device('cpu'), 'cpu', False


# ── Loss ───────────────────────────────────────────────────────────────────────

class _FocalLoss(nn.Module):
    def __init__(self, alpha: torch.Tensor | None = None, gamma: float = 1.5):
        super().__init__()
        self.register_buffer('alpha', alpha)
        self.gamma = gamma

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        ce = nn.functional.cross_entropy(logits, target, reduction='none')
        pt = torch.exp(-ce)
        if self.alpha is not None:
            ce = ce * self.alpha[target]
        return ((1.0 - pt) ** self.gamma * ce).mean()


# ── Training ───────────────────────────────────────────────────────────────────

def train(device_name: str = 'auto', epochs: int = EPOCHS, patience: int = PATIENCE) -> None:
    device, _, pin = resolve_device(device_name)
    train_ds, val_ds, _test_ds, _scaler = build_fault_dataset()

    labels = train_ds.y.numpy()
    counts = np.bincount(labels, minlength=N_CLASSES).astype(np.float32)
    alpha  = torch.tensor(1.0 / np.sqrt(np.maximum(counts, 1.0)), dtype=torch.float32, device=device)
    alpha  = alpha / alpha.mean()
    criterion = _FocalLoss(alpha=alpha)

    train_loader = make_balanced_loader(
        _AugDataset(train_ds, augment=True),  batch_size=BATCH_SIZE, num_workers=0, pin_memory=pin)
    val_loader   = make_val_loader(
        _AugDataset(val_ds,   augment=False), batch_size=512,        num_workers=0, pin_memory=pin)

    model = MSFFN().to(device)
    opt   = Adam(model.parameters(), lr=LR, weight_decay=1e-5)
    sched = CosineAnnealingLR(opt, T_max=epochs, eta_min=1e-5)

    total_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f'MSFFN parameters: {total_params:,}')

    best_f1, patience_cnt = -1.0, 0
    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            loss = criterion(model(x), y)
            opt.zero_grad(); loss.backward(); opt.step()
            total_loss += loss.item()
        sched.step()

        model.eval()
        preds, trues = [], []
        with torch.no_grad():
            for x, y in val_loader:
                preds.extend(model(x.to(device)).argmax(1).cpu().numpy())
                trues.extend(y.numpy())

        val_f1  = f1_score(trues, preds, average='macro', zero_division=0)
        val_acc = accuracy_score(trues, preds)
        print(f'epoch={epoch:03d}  loss={total_loss:.3f}  '
              f'val_acc={100*val_acc:.2f}%  val_macroF1={100*val_f1:.2f}%')

        if val_f1 > best_f1:
            best_f1 = val_f1
            torch.save({'model_state': model.state_dict(), 'arch': 'msffn',
                        'epoch': epoch, 'val_macro_f1': val_f1}, CKPT_PATH)
            patience_cnt = 0
        else:
            patience_cnt += 1
            if patience_cnt >= patience:
                print(f'Early stopping at epoch {epoch} (best Macro F1 {100*best_f1:.2f}%)')
                break

    print(f'\nBest validation Macro F1: {100*best_f1:.2f}%')
    print(f'Checkpoint saved → {CKPT_PATH}')


# ── Evaluation ─────────────────────────────────────────────────────────────────

def evaluate(device_name: str = 'auto') -> dict | None:
    if not CKPT_PATH.exists():
        return None
    device, resolved, pin = resolve_device(device_name)
    _train_ds, _val_ds, test_ds, _scaler = build_fault_dataset()
    loader = make_val_loader(test_ds, batch_size=512, num_workers=0, pin_memory=pin)

    model = MSFFN().to(device)
    ckpt  = torch.load(CKPT_PATH, map_location='cpu')
    model.load_state_dict(ckpt['model_state'])
    model.eval()

    preds, trues = [], []
    with torch.no_grad():
        for x, y in loader:
            preds.extend(model(x.to(device)).argmax(1).cpu().numpy())
            trues.extend(y.numpy())

    y_true, y_pred = np.asarray(trues), np.asarray(preds)
    report = classification_report(
        y_true, y_pred,
        labels=list(range(N_CLASSES)),
        target_names=[FAULT_CLASSES[i] for i in range(N_CLASSES)],
        output_dict=True, zero_division=0,
    )
    return {
        'method':            'AI-MSFFN',
        'family':            'AI',
        'accuracy_pct':      round(100 * accuracy_score(y_true, y_pred), 2),
        'macro_f1_pct':      round(100 * report['macro avg']['f1-score'], 2),
        'weighted_f1_pct':   round(100 * report['weighted avg']['f1-score'], 2),
        'detect_latency_ms': round(WINDOW_SIZE / 20_000 * 1000, 3),
        'classification_report': report,
        'confusion_matrix':  confusion_matrix(
            y_true, y_pred, labels=list(range(N_CLASSES))).tolist(),
        'checkpoint':        str(CKPT_PATH),
        'device':            resolved,
    }


def print_branch_importance(device_name: str = 'auto') -> None:
    """Print average gate weights per fault class to show which branch dominates."""
    if not CKPT_PATH.exists():
        print('No checkpoint found.')
        return
    device, _, pin = resolve_device(device_name)
    _train_ds, _val_ds, test_ds, _scaler = build_fault_dataset()
    loader = make_val_loader(test_ds, batch_size=512, num_workers=0, pin_memory=pin)

    model = MSFFN().to(device)
    model.load_state_dict(torch.load(CKPT_PATH, map_location='cpu')['model_state'])
    model.eval()

    weights_by_class: dict[int, list] = {i: [] for i in range(N_CLASSES)}
    with torch.no_grad():
        for x, y in loader:
            w = model.branch_weights(x.to(device)).cpu().numpy()
            for i, label in enumerate(y.numpy()):
                weights_by_class[label].append(w[i])

    print('\nBranch gate weights (stat / fft / tcn) by fault class:')
    for cls_id, cls_name in FAULT_CLASSES.items():
        if weights_by_class[cls_id]:
            avg = np.mean(weights_by_class[cls_id], axis=0)
            print(f'  {cls_name:15s}  stat={avg[0]:.3f}  fft={avg[1]:.3f}  tcn={avg[2]:.3f}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--train',    action='store_true')
    parser.add_argument('--eval',     action='store_true')
    parser.add_argument('--branches', action='store_true', help='Print gate-weight importance')
    parser.add_argument('--device',   default='auto')
    parser.add_argument('--epochs',   type=int, default=EPOCHS)
    parser.add_argument('--patience', type=int, default=PATIENCE)
    args = parser.parse_args()

    if args.train:
        train(args.device, epochs=args.epochs, patience=args.patience)
    if args.eval or not args.train:
        result = evaluate(args.device)
        if result is None:
            print('No checkpoint found — run with --train first.')
        else:
            print(f"\nTest Accuracy  : {result['accuracy_pct']:.2f}%")
            print(f"Macro F1       : {result['macro_f1_pct']:.2f}%")
            print(f"Weighted F1    : {result['weighted_f1_pct']:.2f}%")
    if args.branches:
        print_branch_importance(args.device)
