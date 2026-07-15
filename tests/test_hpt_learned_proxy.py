import numpy as np
import torch

from version_2.sac.train_hpt_learned_proxy import (
    ProbabilisticRegressor,
    normalization_stats,
    normalize,
    predict_ensemble,
)


def test_learned_proxy_normalization_and_prediction_shapes():
    X = np.asarray(
        [
            [1.0, 0.0, 0.9, 0.1],
            [0.0, 1.0, 1.0, 0.0],
            [1.0, 0.0, 1.1, -0.1],
        ],
        dtype=np.float32,
    )
    Y = np.asarray(
        [
            [0.95, 1.0],
            [1.00, 0.9],
            [1.05, 0.8],
        ],
        dtype=np.float32,
    )
    stats = normalization_stats(X, Y, np.asarray([0, 1], dtype=np.int64))
    Xn = normalize(X, stats["x_mean"], stats["x_std"])

    model = ProbabilisticRegressor(input_dim=4, output_dim=2, hidden=8, depth=1)
    mean, logvar = model(torch.as_tensor(Xn))
    assert mean.shape == (3, 2)
    assert logvar.shape == (3, 2)

    pred = predict_ensemble([model, model], Xn, stats)
    assert pred["mean"].shape == (3, 2)
    assert pred["total_var"].shape == (3, 2)
    assert np.all(np.isfinite(pred["mean"]))
    assert np.all(pred["total_var"] >= 0.0)
