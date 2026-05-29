"""
Train a small DNN controller to imitate the measured rule-based FRT policy.

The exported MATLAB function is intentionally tiny so it can be called from
Simulink MATLAB Function blocks without bringing Python into the loop.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.optim import Adam
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_ROOT / 'data' / 'models'
RESULTS_DIR = PROJECT_ROOT / 'results'
SIMULINK_DIR = PROJECT_ROOT / 'simulink'
MODEL_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

CKPT = MODEL_DIR / 'dnn_frt_imitation.pt'
MATLAB_POLICY = SIMULINK_DIR / 'dnn_frt_policy.m'
REPORT = RESULTS_DIR / 'dnn_frt_imitation_report.json'


class TinyFRTNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(8, 24),
            nn.Tanh(),
            nn.Linear(24, 24),
            nn.Tanh(),
            nn.Linear(24, 2),
        )

    def forward(self, x):
        return self.net(x)


def rule_policy(vdc_pu, v2_pu, i2_pu, sc_id):
    """Return [m_sh, m_se] matching the current rule-FRT Simulink logic."""
    evdc = 1.0 - vdc_pu
    m_sh = 0.68 + 0.30 * evdc
    sag = np.maximum(0.0, 0.98 - v2_pu)
    m_se = np.clip(0.045 + 0.42 * sag, 0.02, 0.24)

    is_short = np.isin(sc_id, [6, 7])
    m_sh = np.where(is_short, np.minimum(m_sh, 0.32), m_sh)
    m_se = np.where(is_short, 0.015, m_se)

    m_sh = np.where((vdc_pu > 1.15) | (i2_pu > 2.0), np.minimum(m_sh, 0.25), m_sh)
    m_sh = np.where((vdc_pu > 1.3125) | (i2_pu > 3.0), np.minimum(m_sh, 0.12), m_sh)
    m_se = np.where(i2_pu > 2.0, np.minimum(m_se, 0.02), m_se)

    m_sh = np.clip(m_sh, 0.0, 0.92)
    m_se = np.clip(m_se, 0.0, 0.28)
    return np.column_stack([m_sh, m_se]).astype(np.float32)


def build_dataset(n=120_000, seed=7):
    rng = np.random.default_rng(seed)
    sc_id = rng.choice([0, 3, 4, 5, 6, 7, 8], size=n)
    vdc = rng.uniform(0.75, 1.45, size=n)
    v2 = rng.uniform(0.15, 1.10, size=n)
    i2 = rng.uniform(0.0, 4.0, size=n)
    fault = rng.uniform(0.0, 1.0, size=n)
    is_short = np.isin(sc_id, [6, 7]).astype(np.float32)
    is_cap = (sc_id == 5).astype(np.float32)
    is_igbt = np.isin(sc_id, [3, 4]).astype(np.float32)
    is_cascade = (sc_id == 8).astype(np.float32)

    x = np.column_stack([
        vdc,
        v2,
        i2,
        fault,
        sc_id / 8.0,
        is_short,
        is_cap,
        is_igbt + is_cascade,
    ]).astype(np.float32)
    y = rule_policy(vdc, v2, i2, sc_id)
    return x, y


def train(epochs=250, device='auto'):
    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    elif device == 'dml':
        import torch_directml
        device = torch_directml.device()
    x, y = build_dataset()
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=42)

    sx = StandardScaler()
    sy = StandardScaler()
    x_train_s = sx.fit_transform(x_train).astype(np.float32)
    x_test_s = sx.transform(x_test).astype(np.float32)
    y_train_s = sy.fit_transform(y_train).astype(np.float32)
    y_test_s = sy.transform(y_test).astype(np.float32)

    model = TinyFRTNet().to(device)
    opt = Adam(model.parameters(), lr=2e-3, weight_decay=1e-5)
    loss_fn = nn.MSELoss()
    xt = torch.from_numpy(x_train_s).to(device)
    yt = torch.from_numpy(y_train_s).to(device)
    xv = torch.from_numpy(x_test_s).to(device)
    yv = torch.from_numpy(y_test_s).to(device)

    best = float('inf')
    best_state = None
    for epoch in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(len(xt), device=device)
        losses = []
        for start in range(0, len(xt), 2048):
            idx = perm[start:start + 2048]
            pred = model(xt[idx])
            loss = loss_fn(pred, yt[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(float(loss.detach().cpu()))
        model.eval()
        with torch.no_grad():
            val = float(loss_fn(model(xv), yv).detach().cpu())
        if val < best:
            best = val
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        if epoch <= 5 or epoch % 25 == 0:
            print(f'epoch={epoch:03d} train_mse={np.mean(losses):.6f} val_mse={val:.6f}')

    print('closed-loop fine tuning...')
    fine_tune_closed_loop(model, sx, sy, device, steps=220)

    model.load_state_dict(best_state)
    fine_tune_closed_loop(model, sx, sy, device, steps=120)
    model.eval()
    with torch.no_grad():
        pred_s = model(xv).cpu().numpy()
    pred = sy.inverse_transform(pred_s)
    mae = mean_absolute_error(y_test, pred, multioutput='raw_values')
    max_err = np.max(np.abs(y_test - pred), axis=0)

    torch.save({
        'model_state': model.state_dict(),
        'x_mean': sx.mean_.astype(np.float32),
        'x_scale': sx.scale_.astype(np.float32),
        'y_mean': sy.mean_.astype(np.float32),
        'y_scale': sy.scale_.astype(np.float32),
        'mae': mae.astype(np.float32),
        'max_err': max_err.astype(np.float32),
    }, CKPT)
    export_matlab_policy(model, sx, sy)

    report = {
        'checkpoint': str(CKPT),
        'matlab_policy': str(MATLAB_POLICY),
        'mae_m_sh': float(mae[0]),
        'mae_m_se': float(mae[1]),
        'max_err_m_sh': float(max_err[0]),
        'max_err_m_se': float(max_err[1]),
        'best_val_mse_scaled': best,
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


def policy_physical(model, sx, sy, x_phys):
    xm = torch.tensor(sx.mean_, dtype=torch.float32, device=x_phys.device)
    xs = torch.tensor(sx.scale_, dtype=torch.float32, device=x_phys.device)
    ym = torch.tensor(sy.mean_, dtype=torch.float32, device=x_phys.device)
    ys = torch.tensor(sy.scale_, dtype=torch.float32, device=x_phys.device)
    y_scaled = model((x_phys - xm) / xs)
    y = y_scaled * ys + ym
    m_sh = torch.clamp(y[:, 0], 0.0, 0.92)
    m_se = torch.clamp(y[:, 1], 0.0, 0.28)
    return m_sh, m_se


def fine_tune_closed_loop(model, sx, sy, device, steps=500):
    opt = Adam(model.parameters(), lr=5e-4, weight_decay=1e-5)
    rng = np.random.default_rng(123)
    batch = 512
    for step in range(1, steps + 1):
        sc_np = rng.choice([0, 3, 4, 5, 6, 7, 8], size=batch)
        sc = torch.tensor(sc_np, dtype=torch.float32, device=device)
        is_short = torch.tensor(np.isin(sc_np, [6, 7]).astype(np.float32), device=device)
        is_cap = torch.tensor((sc_np == 5).astype(np.float32), device=device)
        is_faulty = torch.tensor(np.isin(sc_np, [3, 4, 8]).astype(np.float32), device=device)

        vdc = torch.tensor(rng.uniform(0.86, 1.14, batch), dtype=torch.float32, device=device)
        v2 = torch.tensor(rng.uniform(0.75, 1.02, batch), dtype=torch.float32, device=device)
        i2 = torch.tensor(rng.uniform(0.8, 1.9, batch), dtype=torch.float32, device=device)
        short_depth = torch.tensor(rng.uniform(0.25, 0.72, batch), dtype=torch.float32, device=device)
        cap_drift = torch.tensor(rng.uniform(0.04, 0.16, batch), dtype=torch.float32, device=device)

        vdc_min = vdc
        vdc_max = vdc
        i2_max = i2
        recovery_acc = torch.zeros_like(v2)
        imitation_loss = torch.zeros((), device=device)

        for k in range(16):
            fault = torch.ones_like(vdc)
            x = torch.stack([
                vdc, v2, i2, fault, sc / 8.0,
                is_short, is_cap, is_faulty,
            ], dim=1)
            m_sh, m_se = policy_physical(model, sx, sy, x)
            y_rule_np = rule_policy(
                vdc.detach().cpu().numpy(),
                v2.detach().cpu().numpy(),
                i2.detach().cpu().numpy(),
                sc_np,
            )
            y_rule = torch.tensor(y_rule_np, dtype=torch.float32, device=device)
            # Keep the learned policy near the safe rule, but allow optimization.
            imitation_loss = imitation_loss + 0.08 * torch.mean(
                (m_sh - y_rule[:, 0]) ** 2 + (m_se - y_rule[:, 1]) ** 2)

            # Surrogate closed-loop dynamics: enough to punish bad control trends.
            external_sag = is_short * short_depth + is_cap * 0.02 + is_faulty * 0.06
            support = 0.55 * m_se + 0.10 * torch.relu(m_sh - 0.35)
            v2 = v2 + 0.18 * (1.0 - v2) + support - 0.16 * external_sag
            v2 = torch.clamp(v2, 0.05, 1.20)

            target_m = 0.50 + 0.35 * torch.relu(0.88 - vdc) - 0.30 * torch.relu(vdc - 1.08)
            vdc = vdc + 0.18 * (m_sh - target_m) - 0.04 * torch.relu(i2 - 2.0) - is_cap * cap_drift * 0.03
            vdc = torch.clamp(vdc, 0.35, 1.45)

            i2 = 0.95 + 3.4 * torch.relu(0.88 - v2) + 0.45 * m_sh - 1.4 * m_se
            i2 = torch.clamp(i2, 0.05, 4.5)

            vdc_min = torch.minimum(vdc_min, vdc)
            vdc_max = torch.maximum(vdc_max, vdc)
            i2_max = torch.maximum(i2_max, i2)
            recovery_acc = recovery_acc + torch.relu(0.90 - v2)

        loss_vdc_low = torch.mean(torch.relu(0.80 - vdc_min) ** 2) * 18.0
        loss_vdc_high = torch.mean(torch.relu(vdc_max - 1.18) ** 2) * 12.0
        loss_i = torch.mean(torch.relu(i2_max - 2.75) ** 2) * 5.0
        loss_rec = torch.mean(recovery_acc / 16.0) * 3.0
        loss_effort = torch.mean(0.02 * m_sh ** 2 + 0.03 * m_se ** 2)
        loss = loss_vdc_low + loss_vdc_high + loss_i + loss_rec + loss_effort + imitation_loss

        opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()

        if step <= 5 or step % 100 == 0:
            print(
                f'  ft={step:04d} loss={float(loss.detach().cpu()):.5f} '
                f'vdc_min={float(vdc_min.mean().detach().cpu()):.3f} '
                f'vdc_max={float(vdc_max.mean().detach().cpu()):.3f} '
                f'i2max={float(i2_max.mean().detach().cpu()):.3f}'
            )


def matlab_array(name, arr):
    flat = np.asarray(arr).reshape(-1)
    body = ' '.join(f'{v:.9g}' for v in flat)
    shape = np.asarray(arr).shape
    if len(shape) == 1:
        return f'{name} = [{body}];'
    return f'{name} = reshape([{body}], {shape[0]}, {shape[1]});'


def export_matlab_policy(model, sx, sy):
    sd = model.state_dict()
    w1 = sd['net.0.weight'].cpu().numpy()
    b1 = sd['net.0.bias'].cpu().numpy()
    w2 = sd['net.2.weight'].cpu().numpy()
    b2 = sd['net.2.bias'].cpu().numpy()
    w3 = sd['net.4.weight'].cpu().numpy()
    b3 = sd['net.4.bias'].cpu().numpy()

    lines = [
        'function [m_sh, m_se] = dnn_frt_policy(vdc_pu, v2_pu, i2_pu, fault, sc_id)',
        '%#codegen',
        '% Auto-generated by ai/train_dnn_frt_imitation.py',
        '% Tiny DNN imitation of the rule-based FRT modulation policy.',
        'x = [vdc_pu; v2_pu; i2_pu; fault; sc_id/8; double(sc_id==6 || sc_id==7); double(sc_id==5); double(sc_id==3 || sc_id==4 || sc_id==8)];',
        matlab_array('xm', sx.mean_.astype(np.float32)),
        matlab_array('xs', sx.scale_.astype(np.float32)),
        matlab_array('ym', sy.mean_.astype(np.float32)),
        matlab_array('ys', sy.scale_.astype(np.float32)),
        matlab_array('W1', w1.T.astype(np.float32)),
        matlab_array('b1', b1.astype(np.float32)),
        matlab_array('W2', w2.T.astype(np.float32)),
        matlab_array('b2', b2.astype(np.float32)),
        matlab_array('W3', w3.T.astype(np.float32)),
        matlab_array('b3', b3.astype(np.float32)),
        'z = (transpose(x(:)) - xm) ./ xs;',
        'h1 = tanh(z * W1 + b1);',
        'h2 = tanh(h1 * W2 + b2);',
        'yscaled = h2 * W3 + b3;',
        'y = yscaled .* ys + ym;',
        'm_sh = min(0.92, max(0.0, y(1)));',
        'm_se = min(0.28, max(0.0, y(2)));',
        'end',
    ]
    MATLAB_POLICY.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Exported MATLAB policy to {MATLAB_POLICY}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs', type=int, default=250)
    parser.add_argument('--device', default='auto')
    args = parser.parse_args()
    train(epochs=args.epochs, device=args.device)
