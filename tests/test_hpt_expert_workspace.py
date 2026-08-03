import json

import pytest

from version_2.sac.expert_workspace import (
    EXPERT_SPECS,
    EXPERTS_ROOT,
    expert_spec,
    expert_workspace,
)


def test_registry_has_exactly_twelve_unique_experts() -> None:
    assert len(EXPERT_SPECS) == 12
    assert len({spec.expert_id for spec in EXPERT_SPECS}) == 12


@pytest.mark.parametrize(
    ("phase_key", "phase_family"),
    [
        ("abc", "balanced"),
        ("balanced", "balanced"),
        ("a", "single_phase"),
        ("b", "single_phase"),
        ("c", "single_phase"),
        ("ab", "two_phase"),
        ("bc", "two_phase"),
        ("ca", "two_phase"),
    ],
)
def test_phase_keys_resolve_to_three_family_types(
    phase_key: str,
    phase_family: str,
) -> None:
    spec = expert_spec("topology2", "LVRT", phase_key)
    assert spec.phase_family == phase_family


def test_workspace_stays_under_version_2_experts() -> None:
    workspace = expert_workspace("topology1", "HVRT", "ab")
    parts = workspace.root.parts
    assert parts[-2:] == ("experts", "topology1_two_phase_hvrt")
    assert workspace.models == workspace.root / "models"
    assert workspace.results == workspace.root / "results"
    assert workspace.manifests == workspace.root / "manifests"


def test_unknown_phase_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported HPT fault phase key"):
        expert_spec("topology1", "LVRT", "ac")


def test_committed_registry_matches_the_twelve_specs() -> None:
    registry = json.loads((EXPERTS_ROOT / "registry.json").read_text(encoding="utf-8"))
    assert registry["expert_count"] == 12
    assert {entry["expert_id"] for entry in registry["experts"]} == {
        spec.expert_id for spec in EXPERT_SPECS
    }
