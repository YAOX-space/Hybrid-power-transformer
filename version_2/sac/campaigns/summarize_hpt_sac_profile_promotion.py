"""Summarize SAC fine-tune profiles against dq-seeded actors.

The script is deliberately evidence-first: it consumes switch-level campaign
CSVs and reports whether a SAC profile actually improves the dq-seeded actor.
It does not treat proxy reward as promotion evidence.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Row:
    case: str
    profile: str
    controller: str
    passed: bool
    reason: str
    score: float
    current_peak: float
    vdc_min: float
    source: Path


def _read_rows(run_dir: Path, profile: str) -> list[Row]:
    csv_path = run_dir / "boundary_comparison_rows.csv"
    out: list[Row] = []
    seen: set[tuple[str, str]] = set()
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            controller = raw.get("controller", "")
            case = raw.get("boundary_label", "")
            key = (case, controller)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Row(
                    case=case,
                    profile=profile,
                    controller=controller,
                    passed=bool(int(float(raw.get("voltage_survival_pass") or 0))),
                    reason=raw.get("voltage_survival_reason", "")
                    or raw.get("fail_reason", ""),
                    score=float(raw.get("control_score") or raw.get("survival_score")),
                    current_peak=float(raw.get("grid_current_peak_pu") or "nan"),
                    vdc_min=float(raw.get("vdc_min") or "nan"),
                    source=csv_path,
                )
            )
    return out


def _fmt(row: Row | None) -> str:
    if row is None:
        return "-"
    status = "PASS" if row.passed else "FAIL"
    reason = row.reason or "-"
    return (
        f"{status}; score={row.score:.3f}; I={row.current_peak:.3f}; "
        f"Vdc_min={row.vdc_min:.1f}; {reason}"
    )


def summarize(inputs: list[tuple[str, Path]], out_dir: Path) -> Path:
    rows: list[Row] = []
    for profile, path in inputs:
        rows.extend(_read_rows(path, profile))

    cases = sorted({row.case for row in rows})
    by_case: dict[str, dict[str, Row]] = {}
    for row in rows:
        key = row.controller
        if row.controller == "dq_seeded_actor_after_sac":
            key = f"sac:{row.profile}"
        by_case.setdefault(row.case, {})[key] = row

    lines = [
        "# SAC Profile Promotion Summary\n\n",
        "Promotion uses switch-level voltage-survival evidence only. A SAC "
        "profile is counted as an improvement if it passes and either the "
        "dq-seeded actor fails, or its switch-level score is lower than the "
        "dq-seeded actor score.\n\n",
        "| case | strong dq | dq-seeded actor | SAC profiles | best SAC improvement |\n",
        "|---|---|---|---|---|\n",
    ]

    stats = {
        "cases": len(cases),
        "seed_pass": 0,
        "best_sac_pass": 0,
        "strict_sac_improvement": 0,
        "sac_loses_seed_pass_best_profile": 0,
    }
    for case in cases:
        controllers = by_case[case]
        seed = controllers.get("dq_seeded_actor_before_sac")
        strong = controllers.get("strong_dq")
        sac_rows = [row for key, row in controllers.items() if key.startswith("sac:")]
        pass_sacs = [row for row in sac_rows if row.passed]
        if pass_sacs:
            best_sac = min(pass_sacs, key=lambda row: row.score)
        else:
            best_sac = min(sac_rows, key=lambda row: row.score) if sac_rows else None
        seed_pass = bool(seed and seed.passed)
        best_pass = bool(best_sac and best_sac.passed)
        stats["seed_pass"] += int(seed_pass)
        stats["best_sac_pass"] += int(best_pass)
        improved = bool(
            seed
            and best_sac
            and best_sac.passed
            and ((not seed.passed) or best_sac.score < seed.score)
        )
        stats["strict_sac_improvement"] += int(improved)
        stats["sac_loses_seed_pass_best_profile"] += int(seed_pass and not best_pass)
        profile_text = "<br>".join(
            f"{row.profile}: {_fmt(row)}" for row in sorted(sac_rows, key=lambda row: row.profile)
        )
        improvement_text = (
            f"{best_sac.profile}: {_fmt(best_sac)}"
            if improved and best_sac is not None
            else "no strict SAC improvement"
        )
        lines.append(
            f"| {case} | {_fmt(strong)} | {_fmt(seed)} | {profile_text} | "
            f"{improvement_text} |\n"
        )

    lines.extend(
        [
            "\n## Aggregate\n\n",
            f"- Cases: {stats['cases']}\n",
            f"- Dq-seeded actor pass: {stats['seed_pass']} / {stats['cases']}\n",
            f"- Best SAC profile pass: {stats['best_sac_pass']} / {stats['cases']}\n",
            "- Strict SAC improvements over dq-seed: "
            f"{stats['strict_sac_improvement']} / {stats['cases']}\n",
            "- Best SAC profile loses seed pass: "
            f"{stats['sac_loses_seed_pass_best_profile']} / {stats['cases']}\n",
        ]
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "sac_profile_promotion_summary.md"
    report.write_text("".join(lines), encoding="utf-8")
    return report


def _parse_input(text: str) -> tuple[str, Path]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("Expected PROFILE=RUN_DIR")
    profile, path = text.split("=", 1)
    return profile, Path(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", type=_parse_input, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.input, args.out_dir)
    print(report)


if __name__ == "__main__":
    main()
