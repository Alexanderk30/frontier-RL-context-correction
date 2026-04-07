"""
Re-grade an existing JSONL run with the current grader. Useful when the
grader's ack patterns are widened — re-running the model is unnecessary
because the transcripts and used_pid are already saved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from grader import grade


def regrade_file(in_path: Path, out_path: Path) -> None:
    n = 0
    changes = 0
    counts: dict[str, int] = {}
    with in_path.open() as fin, out_path.open("w") as fout:
        for line in fin:
            r = json.loads(line)
            old = r.get("outcome")
            if old == "exception":
                counts[old] = counts.get(old, 0) + 1
                n += 1
                fout.write(json.dumps(r) + "\n")
                continue
            # Support both new (used_value) and legacy (used_pid) fields.
            used = r.get("used_value", r.get("used_pid"))
            correct = r.get("correct_value", r.get("correct_pid"))
            stale = r.get("stale_value", r.get("stale_pid"))
            # Try to look up scenario ack patterns from scenarios.py
            try:
                from scenarios import SCENARIOS_BY_NAME
                spec = SCENARIOS_BY_NAME.get(r.get("scenario", ""))
                ack_pats = spec.scenario_ack_patterns if spec else []
            except Exception:
                ack_pats = []
            res = grade(
                used_value=used,
                correct_value=correct,
                stale_value=stale,
                assistant_text_after_correction=r.get(
                    "assistant_text_after_correction", ""
                ),
                scenario_ack_patterns=ack_pats,
            )
            r["outcome"] = res.outcome
            r["acknowledged_correction"] = res.acknowledged_correction
            r["ack_evidence"] = res.ack_evidence
            if res.outcome != old:
                changes += 1
            counts[res.outcome] = counts.get(res.outcome, 0) + 1
            n += 1
            fout.write(json.dumps(r) + "\n")
    print(f"regraded {n} trials in {in_path.name}")
    print(f"  outcome changes: {changes}")
    print("  new outcome counts:")
    for k in sorted(counts):
        print(f"    {k:24} {counts[k]}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("--out", default=None, help="default: <input>.regraded.jsonl")
    args = p.parse_args()
    in_path = Path(args.input)
    if not in_path.exists():
        print(f"no such file: {in_path}", file=sys.stderr)
        return 2
    out_path = (
        Path(args.out)
        if args.out
        else in_path.with_suffix(".regraded.jsonl")
    )
    regrade_file(in_path, out_path)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
