"""
Re-grade an existing v2/v3 PID JSONL run with the current grader.

Use case: I widened the ack patterns in grader.py after running the
neutral sweep. Re-grading lets me reclassify previously-stored
stale_silent trials as acknowledged_but_stale without burning more API
credits to re-run.

Reads `<run>.jsonl` and writes `<run>.regraded.jsonl`.

Only re-grades the outcome bucket and the ack fields. Everything else
(used_pid, transcripts, kill_calls, telemetry_calls, etc.) is preserved
verbatim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from grader import grade


def regrade_file(in_path: Path, out_path: Path) -> dict:
    counts: dict[str, int] = {}
    n = 0
    with in_path.open() as fin, out_path.open("w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            old = r.get("outcome", "?")
            if old == "exception":
                # preserve exception trials untouched
                counts[old] = counts.get(old, 0) + 1
                n += 1
                fout.write(json.dumps(r) + "\n")
                continue
            res = grade(
                used_pid=r.get("used_pid"),
                correct_pid=r.get("correct_pid"),
                stale_pid=r.get("stale_pid"),
                assistant_text_after_correction=r.get(
                    "assistant_text_after_correction", ""
                ),
            )
            r["outcome"] = res.outcome
            r["acknowledged_correction"] = res.acknowledged_correction
            r["ack_evidence"] = res.ack_evidence
            counts[res.outcome] = counts.get(res.outcome, 0) + 1
            n += 1
            fout.write(json.dumps(r) + "\n")
    return {"n": n, "counts": counts}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("input", help="path to a JSONL run file")
    p.add_argument("--out", default=None, help="output path (default: <input>.regraded.jsonl)")
    args = p.parse_args()

    in_path = Path(args.input)
    out_path = (
        Path(args.out)
        if args.out
        else in_path.with_suffix(".regraded.jsonl")
    )
    summary = regrade_file(in_path, out_path)
    print(f"regraded {summary['n']} trials -> {out_path}")
    for k in sorted(summary["counts"]):
        print(f"  {k:24} {summary['counts'][k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
