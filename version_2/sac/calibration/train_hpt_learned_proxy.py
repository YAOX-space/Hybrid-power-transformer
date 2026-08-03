"""Train a probabilistic learned proxy from HPT switch-level sweep data.

This is the first PETS-style proxy artifact for the direct SAC research line.
The current dataset is a compact fixed-action response table, so this trainer
models next response metrics from topology/context/action features.  Later
rollout datasets can reuse the same ensemble shell with obs/action/delta_obs
features.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from version_2.sac.experiment_metadata import sha256_file, write_experiment_metadata


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
DEFAULT_DATA_ROOT = ROOT / "version_2" / "data" / "hpt_switch_rollouts"
DEFAULT_OUT_ROOT = ROOT / "version_2" / "data" / "hpt_learned_proxy"


def latest_dataset(root: Path = DEFAULT_DATA_ROOT) -> Path:
    runs = sorted(Path(root).glob("hpt_switch_dataset_*"), key=lambda p: p.stat().st_mtime)
    for run in reversed(runs):
        if (run / "dataset.npz").exists():
            return run / "dataset.npz"
    raise FileNotFoundError(f"No hpt_switch_dataset_*/dataset.npz found in {root}")


def load_dataset(path: Path) -> dict[str, Any]:
    p = Path(path)
    if p.is_dir():
        p = p / "dataset.npz"
    data = np.load(p, allow_pickle=True)
    required = {"X", "Y", "train_idx", "val_idx", "test_idx", "feature_names", "target_names"}
    missing = required - set(data.files)
    if missing:
        raise ValueError(f"Dataset {p} is missing keys: {sorted(missing)}")
    return {
        "path": p,
        "X": np.asarray(data["X"], dtype=np.float32),
        "Y": np.asarray(data["Y"], dtype=np.float32),
        "train_idx": np.asarray(data["train_idx"], dtype=np.int64),
        "val_idx": np.asarray(data["val_idx"], dtype=np.int64),
        "test_idx": np.asarray(data["test_idx"], dtype=np.int64),
        "feature_names": [str(x) for x in data["feature_names"].tolist()],
        "target_names": [str(x) for x in data["target_names"].tolist()],
    }


def normalization_stats(
    X: np.ndarray,
    Y: np.ndarray,
    train_idx: np.ndarray,
    *,
    eps: float = 1e-6,
) -> dict[str, np.ndarray]:
    x_train = X[train_idx]
    y_train = Y[train_idx]
    x_mean = x_train.mean(axis=0)
    x_std = np.maximum(x_train.std(axis=0), eps)
    y_mean = y_train.mean(axis=0)
    y_std = np.maximum(y_train.std(axis=0), eps)
    return {
        "x_mean": x_mean.astype(np.float32),
        "x_std": x_std.astype(np.float32),
        "y_mean": y_mean.astype(np.float32),
        "y_std": y_std.astype(np.float32),
    }


def normalize(values: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return ((values - mean) / std).astype(np.float32)


class ProbabilisticRegressor(nn.Module):
    """Small Gaussian regressor that predicts normalized mean and log variance."""

    def __init__(
        self,
        input_dim: int,
        output_dim: int,
        *,
        hidden: int = 64,
        depth: int = 3,
        min_logvar: float = -8.0,
        max_logvar: float = 3.0,
    ) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        width = input_dim
        for _ in range(depth):
            layers.append(nn.Linear(width, hidden))
            layers.append(nn.SiLU())
            width = hidden
        layers.append(nn.Linear(width, 2 * output_dim))
        self.net = nn.Sequential(*layers)
        self.output_dim = output_dim
        self.min_logvar = min_logvar
        self.max_logvar = max_logvar

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        out = self.net(x)
        mean, raw_logvar = torch.split(out, self.output_dim, dim=-1)
        logvar = torch.clamp(raw_logvar, self.min_logvar, self.max_logvar)
        return mean, logvar


def gaussian_nll(mean: torch.Tensor, logvar: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    inv_var = torch.exp(-logvar)
    return 0.5 * torch.mean((target - mean).pow(2) * inv_var + logvar)


def train_member(
    member_id: int,
    Xn: np.ndarray,
    Yn: np.ndarray,
    train_idx: np.ndarray,
    *,
    hidden: int,
    depth: int,
    epochs: int,
    batch_size: int,
    lr: float,
    seed: int,
    device: torch.device,
) -> tuple[ProbabilisticRegressor, dict[str, float]]:
    rng = np.random.default_rng(seed + 1009 * member_id)
    torch.manual_seed(seed + 9176 * member_id)
    model = ProbabilisticRegressor(
        Xn.shape[1],
        Yn.shape[1],
        hidden=hidden,
        depth=depth,
    ).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-5)
    bootstrap = rng.choice(train_idx, size=len(train_idx), replace=True)
    losses: list[float] = []
    for _ in range(epochs):
        rng.shuffle(bootstrap)
        for start in range(0, len(bootstrap), batch_size):
            batch_idx = bootstrap[start : start + batch_size]
            xb = torch.as_tensor(Xn[batch_idx], dtype=torch.float32, device=device)
            yb = torch.as_tensor(Yn[batch_idx], dtype=torch.float32, device=device)
            mean, logvar = model(xb)
            loss = gaussian_nll(mean, logvar, yb)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 10.0)
            opt.step()
            losses.append(float(loss.detach().cpu()))
    return model.cpu(), {
        "member": member_id,
        "final_loss": float(losses[-1]) if losses else math.nan,
        "mean_tail_loss": float(np.mean(losses[-20:])) if losses else math.nan,
    }


@torch.no_grad()
def predict_ensemble(
    members: list[ProbabilisticRegressor],
    Xn: np.ndarray,
    stats: dict[str, np.ndarray],
) -> dict[str, np.ndarray]:
    x = torch.as_tensor(Xn, dtype=torch.float32)
    means = []
    ale_vars = []
    for member in members:
        member.eval()
        mean, logvar = member(x)
        means.append(mean.numpy())
        ale_vars.append(np.exp(logvar.numpy()))
    mean_stack = np.stack(means, axis=0)
    ale_stack = np.stack(ale_vars, axis=0)
    mean_norm = mean_stack.mean(axis=0)
    ale_var_norm = ale_stack.mean(axis=0)
    epi_var_norm = mean_stack.var(axis=0)
    total_var_norm = ale_var_norm + epi_var_norm
    y_std = stats["y_std"]
    y_mean = stats["y_mean"]
    return {
        "mean": mean_norm * y_std + y_mean,
        "ale_var": ale_var_norm * (y_std**2),
        "epi_var": epi_var_norm * (y_std**2),
        "total_var": total_var_norm * (y_std**2),
    }


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.size < 3 or float(np.std(a)) < 1e-12 or float(np.std(b)) < 1e-12:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def evaluate_split(
    name: str,
    members: list[ProbabilisticRegressor],
    Xn: np.ndarray,
    Y: np.ndarray,
    idx: np.ndarray,
    stats: dict[str, np.ndarray],
    target_names: list[str],
) -> dict[str, Any]:
    pred = predict_ensemble(members, Xn[idx], stats)
    err = pred["mean"] - Y[idx]
    abs_err = np.abs(err)
    target_metrics = {}
    for i, target in enumerate(target_names):
        target_metrics[target] = {
            "rmse": float(np.sqrt(np.mean(err[:, i] ** 2))),
            "mae": float(np.mean(abs_err[:, i])),
            "max_abs": float(np.max(abs_err[:, i])),
            "uncertainty_error_corr": _safe_corr(
                np.sqrt(np.maximum(pred["total_var"][:, i], 0.0)),
                abs_err[:, i],
            ),
        }
    return {
        "split": name,
        "rows": int(len(idx)),
        "mean_rmse": float(np.mean([m["rmse"] for m in target_metrics.values()])),
        "target_metrics": target_metrics,
    }


def write_prediction_csv(
    path: Path,
    pred: dict[str, np.ndarray],
    truth: np.ndarray,
    idx: np.ndarray,
    target_names: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["row_index"]
    for target in target_names:
        fields.extend([f"{target}_true", f"{target}_pred", f"{target}_sigma"])
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for local_i, row_idx in enumerate(idx):
            row: dict[str, float | int] = {"row_index": int(row_idx)}
            for j, target in enumerate(target_names):
                row[f"{target}_true"] = float(truth[row_idx, j])
                row[f"{target}_pred"] = float(pred["mean"][local_i, j])
                row[f"{target}_sigma"] = float(math.sqrt(max(float(pred["total_var"][local_i, j]), 0.0)))
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--members", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=600)
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()

    dataset_path = args.dataset or latest_dataset(args.dataset_root)
    ds = load_dataset(dataset_path)
    stats = normalization_stats(ds["X"], ds["Y"], ds["train_idx"])
    Xn = normalize(ds["X"], stats["x_mean"], stats["x_std"])
    Yn = normalize(ds["Y"], stats["y_mean"], stats["y_std"])

    if args.device == "cuda":
        device = torch.device("cuda")
    elif args.device == "cpu" or not torch.cuda.is_available():
        device = torch.device("cpu")
    else:
        device = torch.device("cuda")

    members: list[ProbabilisticRegressor] = []
    member_metrics = []
    for member_id in range(args.members):
        member, metrics = train_member(
            member_id,
            Xn,
            Yn,
            ds["train_idx"],
            hidden=args.hidden,
            depth=args.depth,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            seed=args.seed,
            device=device,
        )
        members.append(member)
        member_metrics.append(metrics)

    run_id = args.run_id or f"hpt_learned_proxy_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = args.out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "schema": "hpt-learned-proxy-ensemble-v1",
        "feature_names": ds["feature_names"],
        "target_names": ds["target_names"],
        "stats": {k: v.tolist() for k, v in stats.items()},
        "config": {
            "members": args.members,
            "epochs": args.epochs,
            "hidden": args.hidden,
            "depth": args.depth,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "seed": args.seed,
        },
        "state_dicts": [member.state_dict() for member in members],
    }
    model_path = out_dir / "ensemble.pt"
    torch.save(state, model_path)

    split_metrics = {
        split: evaluate_split(
            split,
            members,
            Xn,
            ds["Y"],
            ds[f"{split}_idx"],
            stats,
            ds["target_names"],
        )
        for split in ("train", "val", "test")
    }
    test_pred = predict_ensemble(members, Xn[ds["test_idx"]], stats)
    write_prediction_csv(out_dir / "test_predictions.csv", test_pred, ds["Y"], ds["test_idx"], ds["target_names"])

    summary = {
        "schema": "hpt-learned-proxy-summary-v1",
        "run_id": run_id,
        "dataset": str(ds["path"]),
        "dataset_hash": sha256_file(ds["path"]),
        "model_path": str(model_path),
        "feature_names": ds["feature_names"],
        "target_names": ds["target_names"],
        "rows": int(ds["X"].shape[0]),
        "split_counts": {
            "train": int(len(ds["train_idx"])),
            "val": int(len(ds["val_idx"])),
            "test": int(len(ds["test_idx"])),
        },
        "member_metrics": member_metrics,
        "metrics": split_metrics,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        out_dir,
        experiment_name="hpt_learned_proxy_train",
        config=state["config"],
        dataset_manifest=ds["path"].parent / "manifest.json",
        extra={
            "summary_path": str(out_dir / "summary.json"),
            "model_path": str(model_path),
            "dataset_hash": summary["dataset_hash"],
        },
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()


