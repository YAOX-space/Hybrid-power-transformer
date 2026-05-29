"""
lstm_fault_detector.py  — Method C
LSTM-based fault detection & classification for the HPT.

Architecture:
  Input:  (batch, WINDOW=100, channels=9)   [V_dc, Ish_dq, I1_abc, I2_abc]
  LSTM:   2-layer bidirectional LSTM, hidden=128
  Head:   Dense(64, ReLU) → Dense(N_CLASSES=7, softmax)

Target:  >95% accuracy, <5ms detection latency (= 100-sample window)

Usage:
  python lstm_fault_detector.py --train        # train from data/raw/*.mat
  python lstm_fault_detector.py --eval         # evaluate saved model
  python lstm_fault_detector.py --detect <mat> # detect fault in a single file
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.optim import Adam
from torch.optim.lr_scheduler import CosineAnnealingLR
from sklearn.metrics import (classification_report, confusion_matrix,
                             accuracy_score)

from data_loader import (build_fault_dataset, make_balanced_loader,
                         make_val_loader, FAULT_CLASSES, N_CLASSES,
                         WINDOW_SIZE, N_FEAT_FAULT, RAW_DIR)

# ── Paths ──────────────────────────────────────────────────────────────────────
MODEL_DIR = Path(__file__).resolve().parent.parent / 'data' / 'models'
MODEL_DIR.mkdir(exist_ok=True)
CKPT_PATH = MODEL_DIR / f'lstm_fault_detector_{RAW_DIR.name}.pt'


def checkpoint_path_for_arch(arch: str) -> Path:
    if arch in ('auto', 'cnn'):
        return CKPT_PATH
    return MODEL_DIR / f'lstm_fault_detector_{RAW_DIR.name}_{arch}.pt'

# ── Hyperparameters ────────────────────────────────────────────────────────────
HIDDEN_SIZE   = 128
NUM_LAYERS    = 2
BIDIRECTIONAL = False          # Causal (online inference) — no future info
DROPOUT       = 0.3
BATCH_SIZE    = 256
LR            = 1e-3
EPOCHS        = 60
PATIENCE      = 10             # Early stopping


class FocalLoss(nn.Module):
    """Cross-entropy variant that focuses training on hard/confusing samples."""

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


def class_weights_from_dataset(dataset, device: torch.device) -> torch.Tensor:
    labels = dataset.y.numpy()
    counts = np.bincount(labels, minlength=N_CLASSES).astype(np.float32)
    weights = 1.0 / np.sqrt(np.maximum(counts, 1.0))
    weights = weights / weights.mean()
    return torch.tensor(weights, dtype=torch.float32, device=device)


def resolve_device(device: str) -> Tuple[torch.device, str, bool]:
    """Resolve cpu/cuda/dml/auto into a torch device and pin-memory setting."""
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
            raise RuntimeError('CUDA was requested, but this PyTorch build cannot access CUDA.')
        torch.backends.cudnn.benchmark = True
        return torch.device('cuda'), 'cuda', True

    if device == 'dml':
        import torch_directml
        return torch_directml.device(), 'dml', False

    if device == 'cpu':
        return torch.device('cpu'), 'cpu', False

    raise ValueError(f'Unsupported device: {device}. Use auto, cuda, dml, or cpu.')


# ══════════════════════════════════════════════════════════════════════════════
class LSTMFaultDetector(nn.Module):
    """
    Two-layer LSTM classifier for real-time fault detection.
    Uses causal (forward-only) LSTM for online deployment.
    """

    def __init__(self, input_size=N_FEAT_FAULT, hidden_size=HIDDEN_SIZE,
                 num_layers=NUM_LAYERS, n_classes=N_CLASSES, dropout=DROPOUT):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
            bidirectional=BIDIRECTIONAL,
        )
        lstm_out = hidden_size * (2 if BIDIRECTIONAL else 1)
        self.classifier = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(lstm_out, 64),
            nn.ReLU(),
            nn.Linear(64, n_classes),
        )

    def forward(self, x):
        # x: (batch, seq_len, input_size)
        lstm_out, _ = self.lstm(x)
        last = lstm_out[:, -1, :]    # take last timestep output
        return self.classifier(last)

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        with torch.no_grad():
            logits = self.forward(x)
            return torch.softmax(logits, dim=-1)


class CNNFaultDetector(nn.Module):
    """GPU-friendly temporal CNN for 5 ms sliding-window fault detection."""

    def __init__(self, input_size=N_FEAT_FAULT, n_classes=N_CLASSES, dropout=DROPOUT):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(input_size, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Conv1d(64, 96, kernel_size=5, padding=4, dilation=2),
            nn.BatchNorm1d(96),
            nn.ReLU(),
            nn.Conv1d(96, 128, kernel_size=5, padding=8, dilation=4),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(dropout),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, n_classes),
        )

    def forward(self, x):
        # x: (batch, seq_len, features) -> (batch, features, seq_len)
        x = x.transpose(1, 2)
        return self.classifier(self.net(x))

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        with torch.no_grad():
            logits = self.forward(x)
            return torch.softmax(logits, dim=-1)


class TCNFaultDetector(nn.Module):
    """Causal temporal convolutional network for 5 ms HPT fault windows."""

    def __init__(self, input_size=N_FEAT_FAULT, n_classes=N_CLASSES, dropout=DROPOUT):
        super().__init__()
        channels = [64, 96, 128, 128]
        layers = []
        in_ch = input_size
        for idx, out_ch in enumerate(channels):
            dilation = 2 ** idx
            pad = (5 - 1) * dilation
            layers += [
                nn.ConstantPad1d((pad, 0), 0.0),
                nn.Conv1d(in_ch, out_ch, kernel_size=5, dilation=dilation),
                nn.BatchNorm1d(out_ch),
                nn.ReLU(),
                nn.Dropout(dropout * 0.5),
            ]
            in_ch = out_ch
        self.tcn = nn.Sequential(*layers)
        self.classifier = nn.Sequential(
            nn.AdaptiveAvgPool1d(1),
            nn.Flatten(),
            nn.Linear(channels[-1], 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, n_classes),
        )

    def forward(self, x):
        x = x.transpose(1, 2)
        return self.classifier(self.tcn(x))

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        with torch.no_grad():
            return torch.softmax(self.forward(x), dim=-1)


class CNNLSTMFaultDetector(nn.Module):
    """CNN front-end plus causal LSTM temporal memory."""

    def __init__(self, input_size=N_FEAT_FAULT, n_classes=N_CLASSES, dropout=DROPOUT):
        super().__init__()
        self.cnn = nn.Sequential(
            nn.Conv1d(input_size, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Conv1d(64, 96, kernel_size=5, padding=2),
            nn.BatchNorm1d(96),
            nn.ReLU(),
        )
        self.lstm = nn.LSTM(
            input_size=96,
            hidden_size=96,
            num_layers=1,
            batch_first=True,
            bidirectional=False,
        )
        self.classifier = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(96, 64),
            nn.ReLU(),
            nn.Linear(64, n_classes),
        )

    def forward(self, x):
        z = self.cnn(x.transpose(1, 2)).transpose(1, 2)
        y, _ = self.lstm(z)
        return self.classifier(y[:, -1, :])

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        with torch.no_grad():
            return torch.softmax(self.forward(x), dim=-1)


def create_model(arch: str, device_name: str) -> nn.Module:
    if arch == 'auto':
        arch = 'cnn' if device_name == 'dml' else 'lstm'
    if arch == 'lstm':
        return LSTMFaultDetector()
    if arch == 'cnn':
        return CNNFaultDetector()
    if arch == 'tcn':
        return TCNFaultDetector()
    if arch == 'cnn_lstm':
        return CNNLSTMFaultDetector()
    raise ValueError(f'Unsupported arch: {arch}. Use auto, lstm, cnn, tcn, or cnn_lstm.')


# ══════════════════════════════════════════════════════════════════════════════
def train(epochs: int = EPOCHS, device: str = 'auto', arch: str = 'auto',
          loss_name: str = 'ce'):
    device, device_name, pin_memory = resolve_device(device)
    if arch == 'auto':
        arch = 'cnn' if device_name == 'dml' else 'lstm'
    ckpt_path = checkpoint_path_for_arch(arch)
    print(f'Training on: {device_name} ({device}), arch={arch}')

    # ── Data ──
    train_ds, val_ds, test_ds, _ = build_fault_dataset()
    train_loader = make_balanced_loader(
        train_ds, batch_size=BATCH_SIZE, num_workers=0, pin_memory=pin_memory)
    val_loader   = make_val_loader(
        val_ds, batch_size=512, num_workers=0, pin_memory=pin_memory)
    test_loader  = make_val_loader(
        test_ds, batch_size=512, num_workers=0, pin_memory=pin_memory)

    # ── Model ──
    model = create_model(arch, device_name).to(device)
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f'Model parameters: {n_params:,}')

    # ── Loss: cross-entropy (balanced via WeightedRandomSampler already) ──
    class_weights = class_weights_from_dataset(train_ds, device)
    print('Class weights:', ' '.join(
        f'{FAULT_CLASSES[i]}={class_weights[i].item():.2f}'
        for i in range(N_CLASSES)))

    if loss_name == 'ce':
        criterion = nn.CrossEntropyLoss()
    elif loss_name == 'weighted_ce':
        criterion = nn.CrossEntropyLoss(weight=class_weights)
    elif loss_name == 'focal':
        criterion = FocalLoss(alpha=class_weights, gamma=1.5)
    else:
        raise ValueError(f'Unsupported loss: {loss_name}. Use ce, weighted_ce, or focal.')
    optimizer = Adam(model.parameters(), lr=LR, weight_decay=1e-5)
    scheduler = CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    best_val_acc = -1.0
    patience_counter = 0
    history = {'train_loss': [], 'val_loss': [], 'val_acc': []}

    print(f'\n{"Epoch":>6}  {"Train Loss":>10}  {"Val Loss":>9}  {"Val Acc":>8}  {"Time":>6}')
    print('-' * 52)

    for epoch in range(1, epochs + 1):
        t0 = time.time()

        # ── Train ──
        model.train()
        train_loss = 0.0
        for X, y in train_loader:
            X, y = X.to(device), y.to(device)
            optimizer.zero_grad()
            logits = model(X)
            loss = criterion(logits, y)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            train_loss += loss.item() * len(y)
        train_loss /= len(train_ds)

        # ── Validate ──
        model.eval()
        val_loss, val_correct = 0.0, 0
        with torch.no_grad():
            for X, y in val_loader:
                X, y = X.to(device), y.to(device)
                logits = model(X)
                val_loss    += criterion(logits, y).item() * len(y)
                val_correct += (logits.argmax(1) == y).sum().item()
        val_loss /= len(val_ds)
        val_acc   = val_correct / len(val_ds)

        scheduler.step()

        history['train_loss'].append(train_loss)
        history['val_loss'].append(val_loss)
        history['val_acc'].append(val_acc)

        elapsed = time.time() - t0
        print(f'{epoch:>6}  {train_loss:>10.4f}  {val_loss:>9.4f}  '
              f'{val_acc*100:>7.2f}%  {elapsed:>5.1f}s')

        # ── Early stopping & checkpoint ──
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            patience_counter = 0
            torch.save({
                'epoch': epoch,
                'model_state': model.state_dict(),
                'val_acc': val_acc,
                'history': history,
                'arch': arch,
            }, ckpt_path)
            print(f'         ✓ Saved (val_acc={val_acc*100:.2f}%)')
        else:
            patience_counter += 1
            if patience_counter >= PATIENCE:
                print(f'\nEarly stopping at epoch {epoch}')
                break

    # ── Final evaluation on test set ──
    print(f'\n=== Test Set Evaluation (best model) ===')
    ckpt = torch.load(ckpt_path, map_location=device)
    model.load_state_dict(ckpt['model_state'])
    evaluate(model, test_loader, device)
    print(f'\nModel saved to: {ckpt_path}')


# ══════════════════════════════════════════════════════════════════════════════
def evaluate(model: LSTMFaultDetector, loader, device: str):
    model.eval()
    all_preds, all_labels = [], []
    with torch.no_grad():
        for X, y in loader:
            X = X.to(device)
            preds = model(X).argmax(1).cpu().numpy()
            all_preds.extend(preds)
            all_labels.extend(y.numpy())

    y_true = np.array(all_labels)
    y_pred = np.array(all_preds)

    acc = accuracy_score(y_true, y_pred)
    print(f'Overall Accuracy: {acc*100:.2f}%')
    print(f'\nClassification Report:')
    print(classification_report(
        y_true, y_pred,
        labels=list(range(N_CLASSES)),
        target_names=list(FAULT_CLASSES.values()),
        zero_division=0))
    cm = confusion_matrix(y_true, y_pred, labels=list(range(N_CLASSES)))
    print('Confusion Matrix:')
    print(cm)

    # Detection latency estimate
    window_ms = WINDOW_SIZE / 20_000 * 1000
    print(f'\nDetection latency (window-based): {window_ms:.1f} ms')

    return acc


# ══════════════════════════════════════════════════════════════════════════════
class OnlineFaultDetector:
    """
    Online (streaming) wrapper for deployment in the control loop.
    Maintains a rolling window buffer and returns fault class + confidence.
    Compatible with both Python real-time loop and MATLAB co-simulation.
    """

    def __init__(self, model_path: Path = CKPT_PATH, device: str = 'cpu'):
        self.device = device
        self.model = LSTMFaultDetector().to(device)
        ckpt = torch.load(model_path, map_location=device)
        self.model.load_state_dict(ckpt['model_state'])
        self.model.eval()

        self.buffer = np.zeros((WINDOW_SIZE, N_FEAT_FAULT), dtype=np.float32)
        self.ptr    = 0
        self.full   = False

        # Load scaler
        import pickle
        scaler_path = CKPT_PATH.parent.parent / 'processed' / 'fault_scaler.pkl'
        with open(scaler_path, 'rb') as f:
            self.scaler = pickle.load(f)

    def push(self, sample: np.ndarray) -> tuple[int, float]:
        """
        Push one sample [V_dc, Ish_d, Ish_q, I1_a, I1_b, I1_c, I2_a, I2_b, I2_c].
        Returns (fault_class, confidence) once buffer is full.
        """
        self.buffer[self.ptr % WINDOW_SIZE] = sample
        self.ptr += 1
        if self.ptr >= WINDOW_SIZE:
            self.full = True

        if not self.full:
            return 0, 1.0   # Not enough data yet → assume normal

        # Normalize
        w = np.roll(self.buffer, -(self.ptr % WINDOW_SIZE), axis=0)
        w_norm = self.scaler.transform(w)   # (100, 9)
        x = torch.from_numpy(w_norm[np.newaxis]).float().to(self.device)

        proba = self.model.predict_proba(x)[0].cpu().numpy()
        fault_class = int(proba.argmax())
        confidence  = float(proba[fault_class])
        return fault_class, confidence

    def reset(self):
        self.buffer[:] = 0
        self.ptr = 0
        self.full = False


# ══════════════════════════════════════════════════════════════════════════════
def save_onnx():
    """Export trained model to ONNX for embedded deployment."""
    model = LSTMFaultDetector()
    ckpt = torch.load(CKPT_PATH, map_location='cpu')
    model.load_state_dict(ckpt['model_state'])
    model.eval()

    dummy = torch.zeros(1, WINDOW_SIZE, N_FEAT_FAULT)
    onnx_path = MODEL_DIR / 'lstm_fault_detector.onnx'
    torch.onnx.export(model, dummy, str(onnx_path),
                      input_names=['signals'],
                      output_names=['fault_logits'],
                      dynamic_axes={'signals': {0: 'batch'}},
                      opset_version=17)
    print(f'ONNX model saved to {onnx_path}')


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='HPT LSTM Fault Detector')
    parser.add_argument('--train',  action='store_true', help='Train model')
    parser.add_argument('--eval',   action='store_true', help='Evaluate saved model')
    parser.add_argument('--onnx',   action='store_true', help='Export to ONNX')
    parser.add_argument('--epochs', type=int, default=EPOCHS)
    parser.add_argument('--device', type=str, default='auto')
    parser.add_argument('--arch', type=str, default='auto',
                        choices=['auto', 'lstm', 'cnn', 'tcn', 'cnn_lstm'])
    parser.add_argument('--loss', type=str, default='ce',
                        choices=['ce', 'weighted_ce', 'focal'])
    args = parser.parse_args()

    if args.train:
        train(epochs=args.epochs, device=args.device, arch=args.arch,
              loss_name=args.loss)
    elif args.eval:
        device, device_name, pin_memory = resolve_device(args.device)
        print(f'Evaluating on: {device_name} ({device})')
        _, _, test_ds, _ = build_fault_dataset()
        loader = make_val_loader(
            test_ds, batch_size=512, num_workers=0, pin_memory=pin_memory)
        arch = args.arch
        if arch == 'auto':
            ckpt = torch.load(CKPT_PATH, map_location=device)
            arch = ckpt.get('arch', 'cnn' if device_name == 'dml' else 'lstm')
        ckpt = torch.load(checkpoint_path_for_arch(arch), map_location=device)
        model = create_model(arch, device_name).to(device)
        model.load_state_dict(ckpt['model_state'])
        evaluate(model, loader, device)
    elif args.onnx:
        save_onnx()
    else:
        parser.print_help()
