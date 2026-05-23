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

import argparse
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.optim import Adam
from torch.optim.lr_scheduler import CosineAnnealingLR
from sklearn.metrics import (classification_report, confusion_matrix,
                             accuracy_score)

from data_loader import (build_fault_dataset, make_balanced_loader,
                         make_val_loader, FAULT_CLASSES, N_CLASSES,
                         WINDOW_SIZE, N_FEAT_FAULT)

# ── Paths ──────────────────────────────────────────────────────────────────────
MODEL_DIR = Path(__file__).parent.parent / 'data' / 'models'
MODEL_DIR.mkdir(exist_ok=True)
CKPT_PATH = MODEL_DIR / 'lstm_fault_detector.pt'

# ── Hyperparameters ────────────────────────────────────────────────────────────
HIDDEN_SIZE   = 128
NUM_LAYERS    = 2
BIDIRECTIONAL = False          # Causal (online inference) — no future info
DROPOUT       = 0.3
BATCH_SIZE    = 256
LR            = 1e-3
EPOCHS        = 60
PATIENCE      = 10             # Early stopping


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


# ══════════════════════════════════════════════════════════════════════════════
def train(epochs: int = EPOCHS, device: str = 'auto'):
    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f'Training on: {device}')

    # ── Data ──
    train_ds, val_ds, test_ds, _ = build_fault_dataset()
    train_loader = make_balanced_loader(train_ds, batch_size=BATCH_SIZE)
    val_loader   = make_val_loader(val_ds,   batch_size=512)
    test_loader  = make_val_loader(test_ds,  batch_size=512)

    # ── Model ──
    model = LSTMFaultDetector().to(device)
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f'Model parameters: {n_params:,}')

    # ── Loss: cross-entropy (balanced via WeightedRandomSampler already) ──
    criterion = nn.CrossEntropyLoss()
    optimizer = Adam(model.parameters(), lr=LR, weight_decay=1e-5)
    scheduler = CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    best_val_acc = 0.0
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
            }, CKPT_PATH)
            print(f'         ✓ Saved (val_acc={val_acc*100:.2f}%)')
        else:
            patience_counter += 1
            if patience_counter >= PATIENCE:
                print(f'\nEarly stopping at epoch {epoch}')
                break

    # ── Final evaluation on test set ──
    print(f'\n=== Test Set Evaluation (best model) ===')
    ckpt = torch.load(CKPT_PATH, map_location=device)
    model.load_state_dict(ckpt['model_state'])
    evaluate(model, test_loader, device)
    print(f'\nModel saved to: {CKPT_PATH}')


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
    print(classification_report(y_true, y_pred,
                                target_names=list(FAULT_CLASSES.values()),
                                zero_division=0))
    cm = confusion_matrix(y_true, y_pred)
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
    args = parser.parse_args()

    if args.train:
        train(epochs=args.epochs, device=args.device)
    elif args.eval:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        _, _, test_ds, _ = build_fault_dataset()
        loader = make_val_loader(test_ds, batch_size=512)
        model = LSTMFaultDetector().to(device)
        ckpt = torch.load(CKPT_PATH, map_location=device)
        model.load_state_dict(ckpt['model_state'])
        evaluate(model, loader, device)
    elif args.onnx:
        save_onnx()
    else:
        parser.print_help()
