"""
Aggregates one or more results JSONL files (from run_trials.py) into:

  1. A per-(model, scenario, condition) breakdown of outcomes.
  2. A per-(model, condition) marginal that collapses scenarios.
  3. A target-failure transcript dump (acknowledged_but_stale + stale_silent)
     written to results/failures.jsonl for easy reading.

Usage:
    python summarize.py results/run_*.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


OUTCOME_ORDER = (
    "correct",
    "acknowledged_but_stale",
    "stale_silent",
    "confused",
    "no_action",
    "exception",
)


def load(paths: list[str]) -> list[dict]:
    out = []
    for p in paths:
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
    return out


def _print_table(rows: list[tuple[str, dict[str, int]]], col0_label: str) -> None:
    headers = [col0_label, "n", *OUTCOME_ORDER]
    widths = [max(28, len(col0_label)), 5, 9, 18, 14, 10, 10, 10]
    line = "".join(h.rjust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * sum(widths))
    for label, counts in rows:
        n = sum(counts.values())
        cells = [label.ljust(widths[0]), str(n).rjust(widths[1])]
        for outcome, w in zip(OUTCOME_ORDER, widths[2:]):
            v = counts.get(outcome, 0)
            cells.append(str(v).rjust(w))
        print("".join(cells))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="+")
    p.add_argument(
        "--failures-out",
        default="results/failures.jsonl",
        help="where to dump stale-value failure transcripts",
    )
    args = p.parse_args()

    records = load(args.paths)
    if not records:
        print("no records loaded")
        return 1

    # Per (model, scenario, condition)
    by_full: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    by_cond: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    by_dist: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    by_src: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    by_variant: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    overall: dict[str, int] = defaultdict(int)

    for r in records:
        model = r.get("model", "?")
        scn = r.get("scenario", "?")
        cond = r.get("condition", "?")
        dist = r.get("distance", "?")
        src = r.get("source", r.get("modality", "?"))
        variant = r.get("variant", r.get("version", "?"))
        outcome = r.get("outcome", "?")
        by_full[(model, scn, cond)][outcome] += 1
        by_cond[(model, cond)][outcome] += 1
        by_dist[(model, dist)][outcome] += 1
        by_src[(model, src)][outcome] += 1
        by_variant[(model, variant)][outcome] += 1
        overall[outcome] += 1

    print("\n== per (model, scenario, condition) ==")
    rows = sorted(by_full.items())
    _print_table(
        [(f"{m}/{s}/{c}", counts) for (m, s, c), counts in rows],
        "model/scenario/condition",
    )

    print("\n== per (model, condition) ==")
    rows = sorted(by_cond.items())
    _print_table([(f"{m}/{c}", counts) for (m, c), counts in rows], "model/condition")

    print("\n== per (model, distance) ==")
    rows = sorted(by_dist.items())
    _print_table([(f"{m}/{d}", counts) for (m, d), counts in rows], "model/distance")

    print("\n== per (model, source) ==")
    rows = sorted(by_src.items())
    _print_table([(f"{m}/{x}", counts) for (m, x), counts in rows], "model/source")

    print("\n== per (model, variant) ==")
    rows = sorted(by_variant.items())
    _print_table([(f"{m}/{x}", counts) for (m, x), counts in rows], "model/variant")

    n_total = sum(overall.values())
    print(f"\n== overall ({n_total} trials) ==")
    for k in OUTCOME_ORDER:
        v = overall.get(k, 0)
        pct = (100 * v / n_total) if n_total else 0
        print(f"  {k:24} {v:>5}  ({pct:5.1f}%)")

    failures = [
        r
        for r in records
        if r.get("outcome") in {"acknowledged_but_stale", "stale_silent"}
    ]
    Path(args.failures_out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.failures_out, "w") as fh:
        for r in failures:
            fh.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(failures)} stale-value transcripts to {args.failures_out}")

    target_only = [
        r for r in records if r.get("outcome") == "acknowledged_but_stale"
    ]
    print(
        f"  of which {len(target_only)} are the target "
        f"`acknowledged_but_stale` failure mode"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
