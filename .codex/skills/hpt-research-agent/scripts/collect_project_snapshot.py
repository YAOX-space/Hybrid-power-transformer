"""Print a compact HPT repository snapshot for research-agent sessions."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
VERSION_2 = ROOT / "version_2"


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


def main() -> int:
    snapshot = {
        "root": str(ROOT),
        "branch": run_git("branch", "--show-current"),
        "head": run_git("rev-parse", "--short", "HEAD"),
        "status": run_git("status", "--short", "--branch").splitlines()[:80],
        "version_2_dirs": sorted(
            p.name for p in VERSION_2.iterdir() if p.is_dir()
        )
        if VERSION_2.exists()
        else [],
        "canonical_smoke": [
            "py -3 -m version_2.sac.smoke_matlab_engine --dry-run",
            "py -3 -m version_2.sac.smoke_matlab_engine --runner engine --test interface",
        ],
    }
    print(json.dumps(snapshot, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
