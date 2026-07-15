import numpy as np

from version_2.sac.train_hpt_safety_classifier import choose_safe_threshold, label_safety


def test_safety_classifier_labels_dc_link_collapse_as_unsafe():
    target_names = [
        "lv_pu_mean",
        "vdc_pu_mean",
        "vdc_min_pu",
        "vdc_max_pu",
        "lv_unbalance_pu",
        "energy_i_rms_scaled",
    ]
    Y = np.asarray(
        [
            [1.00, 1.00, 0.95, 1.05, 0.01, 0.0],
            [1.02, 0.45, 0.10, 1.05, 0.01, 0.0],
            [1.35, 1.00, 0.95, 1.05, 0.01, 0.0],
        ],
        dtype=np.float32,
    )

    labels, checks = label_safety(Y, target_names)

    assert labels.tolist() == [1, 0, 0]
    assert checks["vdc_min_survives"].tolist() == [True, False, True]
    assert checks["lv_in_range"].tolist() == [True, True, False]


def test_safety_threshold_prefers_unsafe_recall():
    y_true = np.asarray([0, 0, 1, 1], dtype=np.int64)
    y_score = np.asarray([0.65, 0.69, 0.80, 0.95], dtype=np.float32)

    threshold, metrics = choose_safe_threshold(y_true, y_score, target_unsafe_recall=1.0)

    assert threshold > 0.69
    assert metrics["unsafe_recall"] == 1.0
