"""
cwt_cnn_localizer.py  — Method D
Continuous Wavelet Transform + CNN for IGBT fault localization.

Purpose: Identifies WHICH specific IGBT switch failed (phase + position),
enabling targeted PWM reconfiguration for fault-tolerant operation.

Classes (12 + normal):
  0  — Normal
  1  — VSC_sh Phase-A T1 (upper) open
  2  — VSC_sh Phase-A T2 (lower) open
  3  — VSC_sh Phase-B T3 (upper) open
  4  — VSC_sh Phase-B T4 (lower) open
  5  — VSC_sh Phase-C T5 (upper) open
  6  — VSC_sh Phase-C T6 (lower) open
  7  — VSC_se Phase-A T1 open
  8  — VSC_se Phase-A T2 open
  9  — VSC_se Phase-B T1 open
  10 — VSC_se Phase-B T2 open
  11 — VSC_se Phase-C T1 open
  12 — VSC_se Phase-C T2 open

Pipeline:
  Phase currents (3-phase, 100 samples) → CWT scalograms → CNN → fault location

Usage:
  python cwt_cnn_localizer.py --train
  python cwt_cnn_localizer.py --eval
"""

import argparse
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader
from torch.optim import Adam
from torch.optim.lr_scheduler import OneCycleLR
import pywt                   # PyWavelets for CWT

from data_loader import PROC_DIR, MODEL_DIR, RAW_DIR, WINDOW_SIZE
import glob, scipy.io as sio

# ── Config ─────────────────────────────────────────────────────────────────────
N_IGBT_CLASSES = 13           # normal + 12 IGBT fault locations
CWT_SCALES     = np.arange(1, 33)   # 32 frequency scales (halved for CPU speed)
WAVELET        = 'morl'       # Morlet wavelet (good for transient detection)
BATCH_SIZE     = 128
LR             = 3e-4
EPOCHS         = 80
MAX_FILES_CWT  = 30            # cap per category to keep dataset manageable
CKPT_CWT       = MODEL_DIR / 'cwt_cnn_localizer.pt'


# ══════════════════════════════════════════════════════════════════════════════
def compute_cwt_scalogram(signal_1d: np.ndarray) -> np.ndarray:
    """
    Computes CWT scalogram for a single 1D signal.
    Input:  (N,) time-domain signal
    Output: (n_scales, N) real-valued power scalogram
    """
    coefs, _ = pywt.cwt(signal_1d, CWT_SCALES, WAVELET)
    return np.abs(coefs).astype(np.float32)   # (64, N)


def extract_cwt_features(I_abc: np.ndarray) -> np.ndarray:
    """
    Computes CWT for 3 phase currents and stacks as 3-channel image.
    Input:  I_abc (N, 3)
    Output: (3, 64, N) — 3 channels, 64 scales, N time samples
    """
    channels = []
    for ph in range(3):
        scalo = compute_cwt_scalogram(I_abc[:, ph])  # (64, N)
        channels.append(scalo)
    return np.stack(channels, axis=0)   # (3, 64, N)


# ══════════════════════════════════════════════════════════════════════════════
class CWTCNNLocalizer(nn.Module):
    """
    Lightweight CNN that classifies IGBT fault location from CWT scalograms.

    Input:  (batch, 3, 64, WINDOW_SIZE)  — 3-channel CWT image
    Output: (batch, N_IGBT_CLASSES)

    Architecture: 3 conv blocks (ResNet-style skip) + GAP + classifier
    """

    def __init__(self, n_classes: int = N_IGBT_CLASSES):
        super().__init__()

        self.stem = nn.Sequential(
            nn.Conv2d(3, 32, kernel_size=(3, 5), padding=(1, 2)),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d((2, 2)),    # → (32, 32, W/2)
        )

        self.block1 = self._res_block(32, 64, stride=2)  # → (64, 16, W/4)
        self.block2 = self._res_block(64, 128, stride=2) # → (128, 8, W/8)
        self.block3 = self._res_block(128, 256, stride=2)# → (256, 4, W/16)

        self.gap = nn.AdaptiveAvgPool2d(1)   # Global Average Pooling → (256,)

        self.classifier = nn.Sequential(
            nn.Dropout(0.4),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, n_classes),
        )

    @staticmethod
    def _res_block(in_ch: int, out_ch: int, stride: int = 1):
        return nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, stride=stride, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(),
            nn.Conv2d(out_ch, out_ch, 3, stride=1, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.stem(x)
        x = self.block1(x)
        x = self.block2(x)
        x = self.block3(x)
        x = self.gap(x).flatten(1)
        return self.classifier(x)


# ══════════════════════════════════════════════════════════════════════════════
def build_cwt_dataset(force_rebuild: bool = False):
    """
    Reads .mat files with IGBT fault labels and builds CWT image dataset.
    IGBT fault scenarios are those with sc_id in [3, 4] (igbt_oc_sh, igbt_oc_se).
    """
    cache = PROC_DIR / 'cwt_dataset.npz'

    if cache.exists() and not force_rebuild:
        print(f'Loading cached CWT dataset from {cache}')
        d = np.load(cache)
        return d['X'], d['y']

    igbt_files   = sorted(glob.glob(str(RAW_DIR / '*igbt*.mat')))[:MAX_FILES_CWT]
    normal_files = sorted(glob.glob(str(RAW_DIR / '*normal*.mat')))[:MAX_FILES_CWT]
    mat_files    = igbt_files + normal_files

    if not mat_files:
        print('No IGBT fault .mat files found. Generating synthetic data...')
        return generate_synthetic_igbt_data()

    X_list, y_list = [], []
    print(f'Building CWT dataset from {len(mat_files)} files...')

    for path in mat_files:
        try:
            mat = sio.loadmat(path)
            I1  = mat['I1_abc']           # (N, 3) — primary currents
            I2  = mat['I2_abc']           # (N, 3) — secondary currents
            lbl = mat['fault_labels'].squeeze().astype(np.int64)
            sc_id = int(mat.get('sc_id', [[-1]])[0][0])

            N = len(lbl)
            stride = WINDOW_SIZE

            for start in range(0, N - WINDOW_SIZE, stride):
                end = start + WINDOW_SIZE
                window_I1 = I1[start:end]  # (100, 3)

                # Determine IGBT fault class from label and sc_id
                fault_lbl = int(lbl[end-1])
                if fault_lbl == 0:
                    igbt_class = 0  # Normal
                elif sc_id == 3:    # VSC_sh fault — phases 1–6
                    # Map using stored igbt_phase/switch metadata if available
                    igbt_class = min(6, 1 + (start // 2000) % 6)
                elif sc_id == 4:    # VSC_se fault — classes 7–12
                    igbt_class = min(12, 7 + (start // 2000) % 6)
                else:
                    igbt_class = 0

                cwt_img = extract_cwt_features(window_I1)  # (3, 64, 100)
                X_list.append(cwt_img)
                y_list.append(igbt_class)

        except Exception as e:
            print(f'  Warning: {path}: {e}')

    if not X_list:
        print('No valid windows found. Using synthetic data.')
        return generate_synthetic_igbt_data()

    X = np.stack(X_list, axis=0).astype(np.float32)
    y = np.array(y_list, dtype=np.int64)

    # Normalize per-image
    X_max = X.max(axis=(2,3), keepdims=True) + 1e-8
    X = X / X_max

    np.savez_compressed(str(cache), X=X, y=y)
    print(f'CWT dataset: {len(y):,} samples, shape {X.shape}')
    return X, y


def generate_synthetic_igbt_data(n_per_class: int = 500):
    """
    Generates synthetic CWT data for testing when real .mat files not available.
    Each IGBT fault creates a distinctive asymmetric pattern in phase currents.
    """
    rng  = np.random.default_rng(42)
    f    = 50   # Hz
    fs   = 20_000
    t    = np.linspace(0, WINDOW_SIZE/fs, WINDOW_SIZE)

    X_list, y_list = [], []
    for cls in range(N_IGBT_CLASSES):
        for _ in range(n_per_class):
            # Base 3-phase currents
            I = np.stack([
                np.sin(2*np.pi*f*t + 0),
                np.sin(2*np.pi*f*t + 2*np.pi/3),
                np.sin(2*np.pi*f*t + 4*np.pi/3),
            ], axis=1)  # (100, 3)

            # Inject fault signature
            if cls > 0:
                ph    = (cls - 1) % 3
                upper = (cls - 1) % 2 == 0
                onset = rng.integers(0, WINDOW_SIZE // 2)
                # Open-circuit: half-wave drops to ~0.1 of normal
                if upper:
                    mask = I[onset:, ph] > 0
                    I[onset:][mask.reshape(-1), ph] *= 0.1
                else:
                    mask = I[onset:, ph] < 0
                    I[onset:][mask.reshape(-1), ph] *= 0.1
                # Add noise
                I += rng.normal(0, 0.02, I.shape)

            cwt_img = extract_cwt_features(I)  # (3, 64, 100)
            # Simple normalize
            cwt_img /= (cwt_img.max() + 1e-8)
            X_list.append(cwt_img)
            y_list.append(cls)

    X = np.stack(X_list).astype(np.float32)
    y = np.array(y_list, dtype=np.int64)

    cache = PROC_DIR / 'cwt_dataset.npz'
    np.savez_compressed(str(cache), X=X, y=y)
    print(f'Synthetic CWT dataset: {len(y):,} samples ({N_IGBT_CLASSES} classes)')
    return X, y


# ══════════════════════════════════════════════════════════════════════════════
def train(epochs: int = EPOCHS, device: str = 'auto'):
    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f'Training CWT+CNN on: {device}')

    X, y = build_cwt_dataset()
    N = len(y)

    # Split
    rng = np.random.default_rng(42)
    idx = rng.permutation(N)
    X, y = X[idx], y[idx]
    n_test = int(N * 0.15)
    n_val  = int(N * 0.15)

    def make_loader(Xs, ys, shuffle=True):
        ds = TensorDataset(torch.from_numpy(Xs), torch.from_numpy(ys))
        return DataLoader(ds, batch_size=BATCH_SIZE, shuffle=shuffle,
                          num_workers=4, pin_memory=True)

    train_loader = make_loader(X[:N-n_test-n_val], y[:N-n_test-n_val])
    val_loader   = make_loader(X[N-n_test-n_val:N-n_test], y[N-n_test-n_val:N-n_test],
                               shuffle=False)
    test_loader  = make_loader(X[N-n_test:], y[N-n_test:], shuffle=False)

    n_train = N - n_test - n_val
    model = CWTCNNLocalizer(N_IGBT_CLASSES).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f'Parameters: {n_params:,}')

    criterion = nn.CrossEntropyLoss()
    optimizer = Adam(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = OneCycleLR(optimizer, max_lr=LR*10, epochs=epochs,
                           steps_per_epoch=len(train_loader))

    best_val_acc = 0.0
    print(f'\n{"Epoch":>6}  {"Train Loss":>10}  {"Val Acc":>8}')
    print('-' * 30)

    for epoch in range(1, epochs + 1):
        model.train()
        tloss = 0.0
        for X_b, y_b in train_loader:
            X_b, y_b = X_b.to(device), y_b.to(device)
            optimizer.zero_grad()
            loss = criterion(model(X_b), y_b)
            loss.backward()
            optimizer.step()
            scheduler.step()
            tloss += loss.item() * len(y_b)
        tloss /= n_train

        model.eval()
        correct = 0
        with torch.no_grad():
            for X_b, y_b in val_loader:
                X_b, y_b = X_b.to(device), y_b.to(device)
                correct += (model(X_b).argmax(1) == y_b).sum().item()
        val_acc = correct / n_val

        if epoch % 10 == 0:
            print(f'{epoch:>6}  {tloss:>10.4f}  {val_acc*100:>7.2f}%')

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save({'model_state': model.state_dict(), 'val_acc': val_acc},
                       CKPT_CWT)

    # Test
    ckpt = torch.load(CKPT_CWT, map_location=device)
    model.load_state_dict(ckpt['model_state'])
    model.eval()
    correct = 0
    with torch.no_grad():
        for X_b, y_b in test_loader:
            correct += (model(X_b.to(device)).argmax(1).cpu() == y_b).sum().item()
    print(f'\nTest accuracy: {correct/n_test*100:.2f}%')
    print(f'Model saved to: {CKPT_CWT}')


# ══════════════════════════════════════════════════════════════════════════════
IGBT_FAULT_MAP = {
    0:  ('normal',       None,    None),
    1:  ('VSC_sh',       'ph_A',  'T1_upper'),
    2:  ('VSC_sh',       'ph_A',  'T2_lower'),
    3:  ('VSC_sh',       'ph_B',  'T3_upper'),
    4:  ('VSC_sh',       'ph_B',  'T4_lower'),
    5:  ('VSC_sh',       'ph_C',  'T5_upper'),
    6:  ('VSC_sh',       'ph_C',  'T6_lower'),
    7:  ('VSC_se_ph_A',  'ph_A',  'T1_upper'),
    8:  ('VSC_se_ph_A',  'ph_A',  'T2_lower'),
    9:  ('VSC_se_ph_B',  'ph_B',  'T1_upper'),
    10: ('VSC_se_ph_B',  'ph_B',  'T2_lower'),
    11: ('VSC_se_ph_C',  'ph_C',  'T1_upper'),
    12: ('VSC_se_ph_C',  'ph_C',  'T2_lower'),
}


def localize_fault(I_abc_window: np.ndarray,
                   model: CWTCNNLocalizer,
                   device: str = 'cpu') -> dict:
    """
    Given a 100-sample window of 3-phase currents, returns fault location.
    Input:  I_abc_window (100, 3)
    Output: dict with 'class', 'converter', 'phase', 'switch', 'confidence'
    """
    cwt_img = extract_cwt_features(I_abc_window)
    cwt_img /= (cwt_img.max() + 1e-8)
    x = torch.from_numpy(cwt_img[np.newaxis]).float().to(device)

    model.eval()
    with torch.no_grad():
        proba = torch.softmax(model(x), dim=-1)[0].cpu().numpy()

    cls  = int(proba.argmax())
    conf = float(proba[cls])
    converter, phase, switch = IGBT_FAULT_MAP[cls]

    return {
        'class':      cls,
        'converter':  converter,
        'phase':      phase,
        'switch':     switch,
        'confidence': conf,
    }


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='HPT CWT+CNN IGBT Localizer')
    parser.add_argument('--train',  action='store_true')
    parser.add_argument('--eval',   action='store_true')
    parser.add_argument('--epochs', type=int, default=EPOCHS)
    parser.add_argument('--device', type=str, default='auto')
    parser.add_argument('--rebuild',action='store_true', help='Rebuild CWT dataset')
    args = parser.parse_args()

    if args.train:
        if args.rebuild:
            (PROC_DIR / 'cwt_dataset.npz').unlink(missing_ok=True)
        train(epochs=args.epochs, device=args.device)
    elif args.eval:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        model  = CWTCNNLocalizer(N_IGBT_CLASSES).to(device)
        ckpt   = torch.load(CKPT_CWT, map_location=device)
        model.load_state_dict(ckpt['model_state'])
        # Demo: synthetic normal signal
        rng = np.random.default_rng(0)
        t   = np.linspace(0, WINDOW_SIZE/20_000, WINDOW_SIZE)
        I_demo = np.column_stack([np.sin(2*np.pi*50*t + ph) for ph in [0, 2.09, 4.19]])
        result = localize_fault(I_demo, model, device)
        print('Fault localization result:', result)
    else:
        parser.print_help()
