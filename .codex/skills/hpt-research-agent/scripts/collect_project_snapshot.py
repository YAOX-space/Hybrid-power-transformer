"""Print a compact, evidence-aware HPT repository snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
VERSION_2 = ROOT / "version_2"
CURRENT_STATE = VERSION_2 / "docs" / "autonomy" / "current_research_state.json"
RESEARCH_LOG = VERSION_2 / "docs" / "autonomy" / "logs" / "research_log.md"
EXPERTS = VERSION_2 / "experts"
LEGACY_RESULTS = ROOT / "lab" / "results"


def run_git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    return proc.stdout.strip() if proc.returncode == 0 else proc.stderr.strip()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_current_state() -> dict[str, Any] | None:
    if not CURRENT_STATE.is_file():
        return None
    return json.loads(CURRENT_STATE.read_text(encoding="utf-8"))


def resolve_repo_path(value: str) -> Path:
    return ROOT / Path(value.replace("/", "\\"))


def current_state_checks(state: dict[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {"available": False, "path": str(CURRENT_STATE.relative_to(ROOT))}

    paths: dict[str, str] = dict(state.get("canonical_paths", {}))
    controller = state.get("promoted_controller", {})
    if controller.get("actor_path"):
        paths["promoted_actor"] = controller["actor_path"]
    evidence = state.get("evidence", {})
    expected_hashes: dict[str, str] = {}
    for evidence_name, record in evidence.items():
        if not isinstance(record, dict):
            continue
        if record.get("run_dir"):
            paths[f"evidence_{evidence_name}_run"] = record["run_dir"]
        if record.get("comparison_csv_path"):
            key = f"evidence_{evidence_name}_comparison"
            paths[key] = record["comparison_csv_path"]
            if record.get("comparison_csv_sha256"):
                expected_hashes[key] = record["comparison_csv_sha256"]

    checks: dict[str, Any] = {}
    for name, relative in sorted(paths.items()):
        path = resolve_repo_path(relative)
        checks[name] = {
            "path": relative,
            "exists": path.exists(),
            "sha256": sha256_file(path) if path.is_file() else None,
        }
        if name in expected_hashes:
            checks[name]["hash_matches"] = (
                checks[name]["sha256"] == expected_hashes[name]
            )

    expected_actor_hash = controller.get("actor_sha256")
    actual_actor_hash = checks.get("promoted_actor", {}).get("sha256")
    return {
        "available": True,
        "path": str(CURRENT_STATE.relative_to(ROOT)),
        "updated_at": state.get("updated_at"),
        "claim_scope": state.get("claim_scope"),
        "promoted_controller": controller.get("name"),
        "actor_hash_matches": bool(expected_actor_hash)
        and expected_actor_hash == actual_actor_hash,
        "known_blockers": state.get("known_blockers", []),
        "next_research_gate": state.get("next_research_gate", []),
        "path_checks": checks,
    }


def latest_expert_result_directories(limit: int) -> list[dict[str, Any]]:
    directories: list[tuple[str, Path]] = []
    if EXPERTS.is_dir():
        for expert in EXPERTS.iterdir():
            results = expert / "results"
            if not results.is_dir():
                continue
            directories.extend(
                (expert.name, path)
                for path in results.iterdir()
                if path.is_dir()
            )
    directories.sort(key=lambda item: item[1].stat().st_mtime, reverse=True)
    return [
        {
            "expert_id": expert_id,
            "name": path.name,
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "modified_epoch": int(path.stat().st_mtime),
        }
        for expert_id, path in directories[:limit]
    ]


def latest_legacy_result_directories(limit: int) -> list[dict[str, Any]]:
    if not LEGACY_RESULTS.is_dir():
        return []
    directories = sorted(
        (path for path in LEGACY_RESULTS.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:limit]
    return [
        {
            "name": path.name,
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "modified_epoch": int(path.stat().st_mtime),
        }
        for path in directories
    ]


def latest_log_headings(limit: int) -> list[str]:
    if not RESEARCH_LOG.is_file():
        return []
    headings = [
        line.strip()
        for line in RESEARCH_LOG.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    return headings[-limit:]


def build_snapshot(result_limit: int, log_limit: int) -> dict[str, Any]:
    state = load_current_state()
    return {
        "root": str(ROOT),
        "branch": run_git("branch", "--show-current"),
        "head": run_git("rev-parse", "--short", "HEAD"),
        "status": run_git("status", "--short", "--branch").splitlines()[:80],
        "version_2_dirs": sorted(
            path.name
            for path in VERSION_2.iterdir()
            if path.is_dir() and not path.name.startswith((".", "__"))
        )
        if VERSION_2.exists()
        else [],
        "current_state": current_state_checks(state),
        "latest_research_log_entries": latest_log_headings(log_limit),
        "latest_expert_result_directories": latest_expert_result_directories(
            result_limit
        ),
        "latest_legacy_result_directories": latest_legacy_result_directories(
            min(result_limit, 3)
        ),
        "canonical_commands": [
            "py -3 -m version_2.sac.smoke_matlab_engine --dry-run",
            "py -3 -m version_2.sac.smoke_matlab_engine --runner engine --test interface",
            "py -3 -m version_2.sac.campaigns.run_hpt_family_specialist_matrix --help",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print a compact HPT Git, promoted-state, and evidence snapshot."
    )
    parser.add_argument("--result-limit", type=int, default=8)
    parser.add_argument("--log-limit", type=int, default=8)
    parser.add_argument(
        "--write",
        type=Path,
        help="Optionally write the JSON snapshot to this path as well as stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot = build_snapshot(
        result_limit=max(0, args.result_limit),
        log_limit=max(0, args.log_limit),
    )
    rendered = json.dumps(snapshot, indent=2, ensure_ascii=False)
    if args.write:
        output = args.write if args.write.is_absolute() else ROOT / args.write
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
