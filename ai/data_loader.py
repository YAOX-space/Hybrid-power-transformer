"""
data_loader.py
Loads HPT simulation .mat files, extracts sliding-window samples,
normalizes, and splits into train/val/test sets for PyTorch.

Supported tasks:
  - 'fault_detection'  : LSTM input → fault class label (Methods C, D)
  - 'dnn_control'      : steady-state snapshots → optimal control commands (Method A)
"""

import os
import glob
import numpy as np
import scipy.io as sio
from pathlib import Path
from sklearn.preprocessing import StandardScaler
import torch
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
import pickle

# ── Paths ──────────────────────────────────────────────────────────────────────
RAW_DIR   = Path(__file__).parent.parent / 'data' / 'raw_ode'  # ODE physics-based data
PROC_DIR  = Path(__file__).parent.parent / 'data' / 'processed'
MODEL_DIR = Path(__file__).parent.parent / 'data' / 'models'
PROC_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# ── Constants ──────────────────────────────────────────────────────────────────
F_SAMPLE    = 20_000          # Hz — must match MATLAB run_scenarios.m
WINDOW_SIZE = 100             # samples = 5ms at 20kHz (matches <5ms target)
STRIDE      = 100             # 5ms stride (non-overlapping — keeps memory manageable)
MAX_FILES   = 300             # cap files to keep RAM under ~4 GB
FAULT_CLASSES = {
    0: 'normal',
    1: 'igbt_oc_sh',
    2: 'igbt_oc_se',
    3: 'cap_fault',
    4: 'sc_1ph',
    5: 'sc_3ph',
    6: 'cascade',
}
N_CLASSES = len(FAULT_CLASSES)

# Features for fault detection:  V_dc, I_sh_a/b/c, I_se_a/b/c  → 7 channels
FAULT_FEATURES = ['V_dc', 'Ish_d', 'Ish_q', 'I1_a', 'I1_b', 'I1_c',
                  'I2_a', 'I2_b', 'I2_c']   # 9 channels
N_FEAT_FAULT = len(FAULT_FEATURES)

# Features for DNN controller: V1_rms, V2_rms, V_dc, P1, Q1, P2, mode → 7
CTRL_FEATURES  = ['V1_rms', 'V2_rms', 'V_dc', 'P1', 'Q1', 'P2', 'mode']
CTRL_TARGETS   = ['Vse_d', 'Vse_q', 'Ish_d_cmd']   # 3 control outputs
N_FEAT_CTRL    = len(CTRL_FEATURES)
N_TGT_CTRL     = len(CTRL_TARGETS)


# ══════════════════════════════════════════════════════════════════════════════
class HPTMatLoader:
    """Reads one .mat file and returns structured arrays."""

    def __init__(self, mat_path: str):
        mat = sio.loadmat(mat_path)
        T = mat['t_uniform'].squeeze()
        N = len(T)

        # Voltages and currents
        V1 = mat['V1_abc']          # (N, 3)
        I1 = mat['I1_abc']
        V2 = mat['V2_abc']
        I2 = mat['I2_abc']
        Vdc = mat['V_dc'].squeeze() # (N,)
        Ish = mat['Ish_dq']         # (N, 2)  [d, q]
        Ise = mat['Ise_dq']
        P1  = mat['P1'].squeeze()
        Q1  = mat['Q1'].squeeze()
        P2  = mat['P2'].squeeze()
        Q2  = mat['Q2'].squeeze()
        mode = mat['mode'].squeeze()
        labels = mat['fault_labels'].squeeze().astype(np.int64)

        # RMS voltages (per sample, using single-phase peak/sqrt2 approximation)
        V1_rms = np.sqrt(np.mean(V1**2, axis=1))
        V2_rms = np.sqrt(np.mean(V2**2, axis=1))

        # Pack fault-detection feature matrix  (N, N_FEAT_FAULT)
        self.X_fault = np.column_stack([
            Vdc, Ish[:, 0], Ish[:, 1],
            I1[:, 0], I1[:, 1], I1[:, 2],
            I2[:, 0], I2[:, 1], I2[:, 2],
        ])

        # Pack controller feature matrix  (N, N_FEAT_CTRL)
        self.X_ctrl = np.column_stack([
            V1_rms, V2_rms, Vdc, P1, Q1, P2, mode
        ])

        self.labels = labels
        self.T = T
        self.N = N
        self.sc_label = str(mat.get('sc_label', ['?'])[0])
        self.sc_id    = int(mat.get('sc_id', [[-1]])[0][0])


# ══════════════════════════════════════════════════════════════════════════════
class FaultDetectionDataset(Dataset):
    """
    Sliding-window dataset for LSTM fault detection (Method C).
    Each sample: (WINDOW_SIZE × N_FEAT_FAULT tensor, int label)
    Label = fault class at the END of the window (causal prediction).
    """

    def __init__(self, windows: np.ndarray, labels: np.ndarray):
        # windows: (M, WINDOW_SIZE, N_FEAT_FAULT)
        # labels:  (M,)
        self.X = torch.from_numpy(windows).float()
        self.y = torch.from_numpy(labels).long()

    def __len__(self):
        return len(self.y)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


# ══════════════════════════════════════════════════════════════════════════════
class DNNControlDataset(Dataset):
    """
    Snapshot dataset for DNN multi-mode controller (Method A).
    Each sample: (feature_vector, control_target_vector)
    Loaded from sweep data (not scenario data).
    """

    def __init__(self, X: np.ndarray, Y: np.ndarray):
        self.X = torch.from_numpy(X).float()
        self.Y = torch.from_numpy(Y).float()

    def __len__(self):
        return len(self.Y)

    def __getitem__(self, idx):
        return self.X[idx], self.Y[idx]


# ══════════════════════════════════════════════════════════════════════════════
def build_fault_dataset(
    raw_dir: Path = RAW_DIR,
    window: int = WINDOW_SIZE,
    stride: int = STRIDE,
    val_frac: float = 0.15,
    test_frac: float = 0.15,
    scaler_path: Path = PROC_DIR / 'fault_scaler.pkl',
    force_rebuild: bool = False,
):
    """
    Reads all .mat files, extracts sliding windows, normalizes, splits.
    Returns: (train_ds, val_ds, test_ds, scaler)
    """
    cache = PROC_DIR / 'fault_windows.npz'

    if cache.exists() and not force_rebuild:
        print(f'Loading cached dataset from {cache}')
        d = np.load(cache)
        X_all, y_all = d['X'], d['y']
    else:
        mat_files = sorted(glob.glob(str(raw_dir / '*.mat')))
        if not mat_files:
            raise FileNotFoundError(
                f'No .mat files found in {raw_dir}. Run run_scenarios.m first.')

        # Balance classes: sample evenly across scenario types
        rng_sel = np.random.default_rng(0)
        if len(mat_files) > MAX_FILES:
            mat_files = list(rng_sel.choice(mat_files, MAX_FILES, replace=False))

        X_list, y_list = [], []
        print(f'Loading {len(mat_files)} .mat files (stride={stride})...')

        for path in mat_files:
            try:
                loader = HPTMatLoader(path)
                Xf = loader.X_fault    # (N, 9)
                lbl = loader.labels    # (N,)

                # Sliding windows
                n_windows = (loader.N - window) // stride + 1
                for i in range(n_windows):
                    start = i * stride
                    end   = start + window
                    X_list.append(Xf[start:end])       # (window, 9)
                    y_list.append(int(lbl[end - 1]))    # label at window end
            except Exception as e:
                print(f'  Warning: skipping {path}: {e}')

        X_all = np.stack(X_list, axis=0).astype(np.float32)   # (M, W, 9)
        y_all = np.array(y_list, dtype=np.int64)               # (M,)
        np.savez_compressed(str(cache), X=X_all, y=y_all)
        print(f'  Cached {len(y_all):,} windows to {cache}')

    # Normalize per-channel across all windows
    M, W, C = X_all.shape
    X_flat = X_all.reshape(-1, C)

    if scaler_path.exists() and not force_rebuild:
        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)
    else:
        scaler = StandardScaler()
        scaler.fit(X_flat)
        with open(scaler_path, 'wb') as f:
            pickle.dump(scaler, f)

    X_norm = scaler.transform(X_flat).reshape(M, W, C).astype(np.float32)

    # Shuffle then split
    rng = np.random.default_rng(42)
    idx = rng.permutation(M)
    X_norm, y_all = X_norm[idx], y_all[idx]

    n_test  = int(M * test_frac)
    n_val   = int(M * val_frac)
    n_train = M - n_test - n_val

    X_train, y_train = X_norm[:n_train], y_all[:n_train]
    X_val,   y_val   = X_norm[n_train:n_train+n_val], y_all[n_train:n_train+n_val]
    X_test,  y_test  = X_norm[n_train+n_val:], y_all[n_train+n_val:]

    print(f'Dataset split: train={n_train:,}  val={n_val:,}  test={n_test:,}')
    _print_class_dist('Train', y_train)
    _print_class_dist('Test',  y_test)

    train_ds = FaultDetectionDataset(X_train, y_train)
    val_ds   = FaultDetectionDataset(X_val,   y_val)
    test_ds  = FaultDetectionDataset(X_test,  y_test)

    return train_ds, val_ds, test_ds, scaler


def make_balanced_loader(dataset: FaultDetectionDataset, batch_size: int = 256,
                         num_workers: int = 4) -> DataLoader:
    """Class-balanced sampler to handle rare fault events."""
    labels = dataset.y.numpy()
    class_counts = np.bincount(labels, minlength=N_CLASSES)
    weights = 1.0 / (class_counts[labels] + 1e-8)
    sampler = WeightedRandomSampler(weights, num_samples=len(dataset), replacement=True)
    return DataLoader(dataset, batch_size=batch_size, sampler=sampler,
                      num_workers=num_workers, pin_memory=True)


def make_val_loader(dataset: FaultDetectionDataset, batch_size: int = 512,
                    num_workers: int = 4) -> DataLoader:
    return DataLoader(dataset, batch_size=batch_size, shuffle=False,
                      num_workers=num_workers, pin_memory=True)


def _print_class_dist(name, labels):
    counts = np.bincount(labels, minlength=N_CLASSES)
    print(f'  {name} class distribution:')
    for c, cnt in enumerate(counts):
        print(f'    {FAULT_CLASSES[c]:15s}: {cnt:6d} ({100*cnt/len(labels):.1f}%)')


# ══════════════════════════════════════════════════════════════════════════════
def export_mat_to_numpy():
    """
    Convenience function: converts all .mat files to a single .npz archive
    readable by numpy without MATLAB. Called after run_scenarios.m completes.
    """
    mat_files = sorted(glob.glob(str(RAW_DIR / '*.mat')))
    print(f'Exporting {len(mat_files)} .mat files...')

    all_X, all_y, all_meta = [], [], []
    for path in mat_files:
        loader = HPTMatLoader(path)
        all_X.append(loader.X_fault)
        all_y.append(loader.labels)
        all_meta.append({'sc_id': loader.sc_id, 'sc_label': loader.sc_label})

    out = PROC_DIR / 'all_signals.npz'
    np.savez_compressed(str(out),
                        X=np.vstack(all_X),
                        y=np.concatenate(all_y))
    print(f'Saved to {out}')


if __name__ == '__main__':
    train_ds, val_ds, test_ds, scaler = build_fault_dataset(force_rebuild=True)
    loader = make_balanced_loader(train_ds, batch_size=256)
    x_batch, y_batch = next(iter(loader))
    print(f'\nSample batch — X: {x_batch.shape}, y: {y_batch.shape}')
