import hashlib
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXPERT = ROOT / "version_2" / "experts" / "topology2_single_phase_lvrt"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_curated_manifest_targets_exist_and_match_hashes() -> None:
    manifest = json.loads(
        (EXPERT / "manifests" / "data_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["expert_id"] == "topology2_single_phase_lvrt"
    assert manifest["artifact_count"] == 37
    for artifact in manifest["artifacts"]:
        target = ROOT / artifact["target"]
        assert target.is_file(), target
        assert sha256_file(target) == artifact["sha256"], target


def test_support_anchor_has_promoted_observation_action_contract() -> None:
    path = EXPERT / "data" / "support_anchor" / "family_anchor_joint_support.npz"
    with np.load(path, allow_pickle=False) as payload:
        assert payload["observations"].shape == (25647, 24)
        assert payload["actions"].shape == (25647, 4)


def test_canonical_metadata_uses_portable_expert_paths() -> None:
    anchor = json.loads(
        (
            EXPERT
            / "data"
            / "support_anchor"
            / "family_anchor_joint_support.json"
        ).read_text(encoding="utf-8")
    )
    proxy = json.loads(
        (EXPERT / "proxy" / "model" / "hpt_proxy_calibration.json").read_text(
            encoding="utf-8"
        )
    )
    serialized = json.dumps({"anchor": anchor, "proxy": proxy})
    assert "lab/results" not in serialized
    assert "lab\\results" not in serialized
    assert all(
        item["trace_csv"].startswith("version_2/experts/")
        for item in anchor["source_summaries"]
    )


def test_validation_tables_keep_their_original_row_counts() -> None:
    targeted = EXPERT / "data" / "validation" / "targeted_family_comparison_rows.csv"
    expanded = EXPERT / "data" / "validation" / "expanded_boundary_comparison_rows.csv"
    assert sum(1 for _ in targeted.open(encoding="utf-8-sig")) - 1 == 27
    assert sum(1 for _ in expanded.open(encoding="utf-8-sig")) - 1 == 120
