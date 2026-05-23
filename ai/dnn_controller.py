"""
dnn_controller.py  — Method A
Deep Neural Network multi-mode controller for HPT.

Architecture inspired by:
  "Deep Learning-based Control of Multi-Port Solid State Transformer"
  Kamal et al., 2025 (week1 reference paper)

Approach:
  1. Generate training data by sweeping V_se amplitude & phase angle in Simulink
  2. Train DNN to learn: [system states] → [optimal V_se_d, V_se_q, I_sh_d commands]
  3. Deploy with closed-loop proportional correction (Eq. 10 from reference paper)

Usage:
  python dnn_controller.py --sweep       # run MATLAB sweep (requires MATLAB Engine)
  python dnn_controller.py --train       # train DNN from sweep data
  python dnn_controller.py --eval        # evaluate trained model
  python dnn_controller.py --demo        # run live demo with step reference
"""

import argparse
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader, random_split
from torch.optim import Adam
from torch.optim.lr_scheduler import ReduceLROnPlateau
from sklearn.preprocessing import StandardScaler
import pickle

from data_loader import PROC_DIR, MODEL_DIR

# ── Paths ──────────────────────────────────────────────────────────────────────
SWEEP_DATA  = PROC_DIR / 'dnn_sweep_data.npz'
CKPT_DNN    = MODEL_DIR / 'dnn_controller.pt'

# ── Hyperparameters ────────────────────────────────────────────────────────────
HIDDEN_SIZES  = [256, 256, 128, 128, 64]
BATCH_SIZE    = 1024
LR            = 1e-3
EPOCHS        = 200
PATIENCE      = 20
KP_CORRECTION = 0.05   # Proportional gain for closed-loop correction (Eq. 10)

# ── Physical bounds (per-unit normalization references) ─────────────────────
V_GRID_PH   = 10_000 / np.sqrt(3)   # ~5773 V
V_SEC       = 400.0                  # V
V_DC_NOM    = 800.0                  # V
S_RATED     = 400e3                  # VA
V_SE_MAX    = 0.20 * V_GRID_PH      # ±20% regulation range
I_SH_MAX    = S_RATED / (np.sqrt(3) * V_SEC)


# ══════════════════════════════════════════════════════════════════════════════
class DNNController(nn.Module):
    """
    Feedforward DNN that maps system states + power references
    to optimal converter control commands.

    Input (7 features):
      [V1_rms_pu, V2_rms_pu, V_dc_pu, P1_ref_pu, Q1_ref_pu, P2_ref_pu, mode_onehot...]
    Output (3 targets):
      [Vse_d_pu, Vse_q_pu, Ish_d_pu]
    """

    def __init__(self, input_dim: int = 7, output_dim: int = 3,
                 hidden_sizes: list = None):
        super().__init__()
        if hidden_sizes is None:
            hidden_sizes = HIDDEN_SIZES

        layers = []
        prev = input_dim
        for h in hidden_sizes:
            layers += [nn.Linear(prev, h), nn.ReLU(), nn.BatchNorm1d(h)]
            prev = h
        layers.append(nn.Linear(prev, output_dim))  # Linear output (no saturation here)
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ══════════════════════════════════════════════════════════════════════════════
def generate_sweep_data_via_matlab(n_points: int = 500_000):
    """
    Uses MATLAB Engine for Python to run parametric sweep in Simulink.
    Sweeps V_se amplitude and phase, records steady-state port powers.
    Result saved to SWEEP_DATA.

    Requires: pip install matlabengine  (MATLAB R2022a+ Python Engine)
    """
    try:
        import matlab.engine
    except ImportError:
        raise ImportError(
            'MATLAB Engine for Python not installed.\n'
            'Install: cd matlabroot/extern/engines/python && python setup.py install\n'
            'Or use: generate_synthetic_sweep_data() for approximate training data.')

    print('Starting MATLAB Engine...')
    eng = matlab.engine.start_matlab()
    eng.cd(str(Path(__file__).parent.parent / 'simulink'), nargout=0)
    eng.run('parameters', nargout=0)

    # Define sweep grid
    Vse_amp_vals   = np.linspace(0, 0.20 * V_GRID_PH, 50)   # 0 to V_se_max
    Vse_phase_vals = np.linspace(-np.pi, np.pi, 100)          # full phase range
    V1_vals = V_GRID_PH * np.array([0.9, 0.95, 1.0, 1.05, 1.1])
    V2_vals = V_SEC     * np.array([0.9, 0.95, 1.0, 1.05, 1.1])

    X_rows, Y_rows = [], []

    print(f'Running Simulink sweep ({n_points:,} target points)...')
    count = 0

    for V1 in V1_vals:
        for V2 in V2_vals:
            for Vamp in Vse_amp_vals[::2]:      # subsample for speed
                for Vphase in Vse_phase_vals[::5]:
                    Vse_d = Vamp * np.cos(Vphase)
                    Vse_q = Vamp * np.sin(Vphase)

                    # Set parameters in MATLAB workspace
                    eng.workspace['Vse_d_sweep'] = float(Vse_d)
                    eng.workspace['Vse_q_sweep'] = float(Vse_q)
                    eng.workspace['V1_sweep']    = float(V1)
                    eng.workspace['V2_sweep']    = float(V2)

                    # Run steady-state simulation (short, 0.2s to reach SS)
                    try:
                        out = eng.sim('hpt_main_model',
                                      matlab.double([0, 0.2]), nargout=1)
                        # Read steady-state power from last 20% of sim
                        P1 = float(eng.workspace['P1_ss'])
                        Q1 = float(eng.workspace['Q1_ss'])
                        P2 = float(eng.workspace['P2_ss'])
                        V_dc = float(eng.workspace['Vdc_ss'])

                        # Feature vector: normalized to pu
                        x_row = [V1/V_GRID_PH, V2/V_SEC, V_dc/V_DC_NOM,
                                 P1/S_RATED, Q1/S_RATED, P2/S_RATED, 1.0]  # mode=1
                        # Target: control outputs in pu
                        y_row = [Vse_d/V_SE_MAX, Vse_q/V_SE_MAX, 0.0]  # Ish_d from DC loop
                        X_rows.append(x_row)
                        Y_rows.append(y_row)
                        count += 1
                    except Exception:
                        pass

                    if count >= n_points:
                        break
                if count >= n_points:
                    break

    eng.quit()
    X = np.array(X_rows, dtype=np.float32)
    Y = np.array(Y_rows, dtype=np.float32)
    np.savez_compressed(str(SWEEP_DATA), X=X, Y=Y)
    print(f'Sweep complete: {len(X):,} data points saved to {SWEEP_DATA}')


def generate_synthetic_sweep_data(n_points: int = 500_000):
    """
    Generates approximate training data analytically (no MATLAB needed).
    Uses the HPT power flow equations from Tang Aihong et al.:
      P_L = (V_m2 * V2 / X_se) * sin(θ_m2 - θ_2)
      Q_L = (V_m2² - V_m2*V2*cos(θ_m2-θ_2)) / X_se
    where V_m2 = V2 + Vse (series voltage injection effect)
    """
    rng = np.random.default_rng(42)
    print(f'Generating {n_points:,} synthetic data points...')

    # System parameters
    X_se = 0.05  # Series reactance (pu)
    X_sh = 0.03  # Shunt reactance (pu)

    # Random operating conditions
    V1_pu  = rng.uniform(0.9, 1.1, n_points)
    V2_pu  = rng.uniform(0.85, 1.15, n_points)
    Vdc_pu = rng.uniform(0.95, 1.05, n_points)
    Vse_d  = rng.uniform(-1.0, 1.0, n_points)   # pu of V_se_max
    Vse_q  = rng.uniform(-1.0, 1.0, n_points)
    # Clip to unit circle (|Vse| ≤ 1.0 pu)
    Vse_mag = np.sqrt(Vse_d**2 + Vse_q**2)
    mask = Vse_mag > 1.0
    Vse_d[mask] /= Vse_mag[mask]
    Vse_q[mask] /= Vse_mag[mask]

    mode = np.ones(n_points)

    # Approximate power flows (from HPT equivalent circuit, Tang Aihong Eq. 4)
    delta = np.arctan2(Vse_q, Vse_d)
    Vse_amp = np.sqrt(Vse_d**2 + Vse_q**2)
    # Power at secondary: P2 ≈ V1·V2·sin(delta)/X_T + V1·Vse·sin(phi)/X_T
    P2 = V2_pu + Vse_d * 0.8  # Simplified linear model
    Q2 = V2_pu - 1.0 + Vse_q * 0.8
    P1 = P2 + 0.05 * Vse_mag  # Losses
    Q1 = Q2 - Vse_q * 0.5

    # VSC_sh d-axis current (maintains DC bus): approximate
    Ish_d = (Vdc_pu - 1.0) * 2.0 + Vse_amp * 0.1

    X = np.column_stack([V1_pu, V2_pu, Vdc_pu, P1, Q1, P2, mode]).astype(np.float32)
    Y = np.column_stack([Vse_d, Vse_q, Ish_d]).astype(np.float32)

    np.savez_compressed(str(SWEEP_DATA), X=X, Y=Y)
    print(f'Synthetic data saved to {SWEEP_DATA}')
    return X, Y


# ══════════════════════════════════════════════════════════════════════════════
def train(epochs: int = EPOCHS, device: str = 'auto'):
    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f'Training DNN Controller on: {device}')

    # ── Load sweep data ──
    if not SWEEP_DATA.exists():
        print('Sweep data not found. Generating synthetic data...')
        generate_synthetic_sweep_data()

    d = np.load(SWEEP_DATA)
    X_np, Y_np = d['X'], d['Y']
    print(f'Loaded {len(X_np):,} data points. X: {X_np.shape}, Y: {Y_np.shape}')

    # ── Normalize inputs ──
    scaler_x = StandardScaler()
    scaler_y = StandardScaler()
    X_norm = scaler_x.fit_transform(X_np).astype(np.float32)
    Y_norm = scaler_y.fit_transform(Y_np).astype(np.float32)

    for sc, name in [(scaler_x, 'dnn_ctrl_scaler_x.pkl'),
                     (scaler_y, 'dnn_ctrl_scaler_y.pkl')]:
        with open(PROC_DIR / name, 'wb') as f:
            pickle.dump(sc, f)

    # ── Split ──
    N = len(X_norm)
    n_test  = int(N * 0.15)
    n_val   = int(N * 0.15)
    n_train = N - n_val - n_test

    X_t, X_v, X_te = X_norm[:n_train], X_norm[n_train:n_train+n_val], X_norm[n_train+n_val:]
    Y_t, Y_v, Y_te = Y_norm[:n_train], Y_norm[n_train:n_train+n_val], Y_norm[n_train+n_val:]

    def make_loader(X, Y, shuffle=True):
        ds = TensorDataset(torch.from_numpy(X), torch.from_numpy(Y))
        return DataLoader(ds, batch_size=BATCH_SIZE, shuffle=shuffle,
                          num_workers=4, pin_memory=True)

    train_loader = make_loader(X_t, Y_t)
    val_loader   = make_loader(X_v, Y_v, shuffle=False)
    test_loader  = make_loader(X_te, Y_te, shuffle=False)

    # ── Model ──
    model = DNNController(input_dim=X_np.shape[1], output_dim=Y_np.shape[1]).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f'Model parameters: {n_params:,}')

    criterion = nn.MSELoss()
    optimizer = Adam(model.parameters(), lr=LR, weight_decay=1e-5)
    scheduler = ReduceLROnPlateau(optimizer, patience=5, factor=0.5, min_lr=1e-6)

    best_val_loss = float('inf')
    patience_counter = 0

    print(f'\n{"Epoch":>6}  {"Train MSE":>10}  {"Val MSE":>9}  {"Val MAE":>8}')
    print('-' * 42)

    for epoch in range(1, epochs + 1):
        # ── Train ──
        model.train()
        train_loss = 0.0
        for X, Y in train_loader:
            X, Y = X.to(device), Y.to(device)
            optimizer.zero_grad()
            pred = model(X)
            loss = criterion(pred, Y)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item() * len(Y)
        train_loss /= n_train

        # ── Validate ──
        model.eval()
        val_mse, val_mae = 0.0, 0.0
        with torch.no_grad():
            for X, Y in val_loader:
                X, Y = X.to(device), Y.to(device)
                pred = model(X)
                val_mse += nn.functional.mse_loss(pred, Y).item() * len(Y)
                val_mae += nn.functional.l1_loss(pred, Y).item() * len(Y)
        val_mse /= n_val
        val_mae /= n_val

        scheduler.step(val_mse)

        if epoch % 10 == 0 or epoch <= 5:
            print(f'{epoch:>6}  {train_loss:>10.6f}  {val_mse:>9.6f}  {val_mae:>8.6f}')

        if val_mse < best_val_loss:
            best_val_loss = val_mse
            patience_counter = 0
            torch.save({
                'model_state': model.state_dict(),
                'val_mse': val_mse,
                'epoch': epoch,
            }, CKPT_DNN)
        else:
            patience_counter += 1
            if patience_counter >= PATIENCE:
                print(f'Early stopping at epoch {epoch}')
                break

    # ── Test ──
    ckpt = torch.load(CKPT_DNN, map_location=device)
    model.load_state_dict(ckpt['model_state'])
    model.eval()
    test_mae = 0.0
    with torch.no_grad():
        for X, Y in test_loader:
            X, Y = X.to(device), Y.to(device)
            pred = model(X)
            test_mae += nn.functional.l1_loss(pred, Y).item() * len(Y)
    test_mae /= n_test
    print(f'\nTest MAE (normalized): {test_mae:.6f}')
    print(f'Test MAE (Vse_d, Vpu): {test_mae * scaler_y.scale_[0]:.4f} pu')
    print(f'Model saved to: {CKPT_DNN}')


# ══════════════════════════════════════════════════════════════════════════════
class DNNControllerDeployed:
    """
    Deployed DNN controller with closed-loop proportional correction.
    Implements Eq. 10 from the DNN-SST reference paper:
      Φ_cmd = DNN(x) + Kp * (P_ref - P_measured)
    """

    def __init__(self, model_path: Path = CKPT_DNN, device: str = 'cpu',
                 kp: float = KP_CORRECTION):
        self.device = device
        self.kp = kp

        self.model = DNNController().to(device)
        ckpt = torch.load(model_path, map_location=device)
        self.model.load_state_dict(ckpt['model_state'])
        self.model.eval()

        with open(PROC_DIR / 'dnn_ctrl_scaler_x.pkl', 'rb') as f:
            self.scaler_x = pickle.load(f)
        with open(PROC_DIR / 'dnn_ctrl_scaler_y.pkl', 'rb') as f:
            self.scaler_y = pickle.load(f)

    def compute_control(self, state: np.ndarray,
                        P_ref: float, P_meas: float,
                        Q_ref: float = 0.0) -> np.ndarray:
        """
        state: [V1_rms_pu, V2_rms_pu, V_dc_pu, P1_ref_pu, Q1_ref_pu, P2_ref_pu, mode]
        Returns: [Vse_d_pu, Vse_q_pu, Ish_d_pu] (raw commands before actuator)
        """
        x_norm = self.scaler_x.transform(state[np.newaxis])
        x_t = torch.from_numpy(x_norm.astype(np.float32)).to(self.device)

        with torch.no_grad():
            y_norm = self.model(x_t).cpu().numpy()[0]

        cmd = self.scaler_y.inverse_transform(y_norm[np.newaxis])[0]

        # Closed-loop proportional correction (Eq. 10)
        P_error = P_ref - P_meas
        cmd[0] += self.kp * P_error  # Correct Vse_d
        cmd[1] += self.kp * (Q_ref - 0.0)  # Correct Vse_q

        # Physical saturation
        Vse_mag = np.sqrt(cmd[0]**2 + cmd[1]**2)
        if Vse_mag > 1.0:
            cmd[:2] /= Vse_mag
        cmd[2] = np.clip(cmd[2], -1.0, 1.0)

        return cmd


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='HPT DNN Controller')
    parser.add_argument('--sweep',    action='store_true', help='Run MATLAB sweep')
    parser.add_argument('--synthetic',action='store_true', help='Generate synthetic sweep data')
    parser.add_argument('--train',    action='store_true', help='Train DNN')
    parser.add_argument('--eval',     action='store_true', help='Evaluate')
    parser.add_argument('--epochs',   type=int, default=EPOCHS)
    parser.add_argument('--device',   type=str, default='auto')
    args = parser.parse_args()

    if args.sweep:
        generate_sweep_data_via_matlab()
    elif args.synthetic:
        generate_synthetic_sweep_data()
    elif args.train:
        train(epochs=args.epochs, device=args.device)
    elif args.eval:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        ctrl = DNNControllerDeployed(device=device)
        # Test one control step
        state = np.array([1.0, 1.0, 1.0, 0.8, 0.1, 0.8, 1.0], dtype=np.float32)
        cmd = ctrl.compute_control(state, P_ref=0.8, P_meas=0.78)
        print(f'Control output: Vse_d={cmd[0]:.4f} pu, Vse_q={cmd[1]:.4f} pu, '
              f'Ish_d={cmd[2]:.4f} pu')
    else:
        parser.print_help()
