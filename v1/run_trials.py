"""
Runs Context Override Resistance trials against an Anthropic model
using real tool use against an on-disk synthetic repo.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python run_trials.py --model claude-haiku-4-5 --trials 3
    python run_trials.py --model claude-sonnet-4-6 --trials 3 --scenario db_pool_size

The trial flow for each (scenario, condition) pair:

  T0  setup: fresh temp dir with scenario.starter_files
  T1  user: orientation + task framing + nudge to read source_file
       loop: model may emit tool_use blocks; runner executes them and
             feeds tool_result blocks back
       loop ends when the model stops requesting tools
  T2  user: depending on condition, deliver the correction. Possibly
       insert distractor turns, possibly attach the task in the same
       turn (D0).
  T3+ continue the tool-use loop. Model is expected to call write_file
       on the scenario's target_file. Once it does (or after a step
       budget), the trial ends.
  T4  introspect: read target_file, run grader, save record.

The runner saves a JSONL line per trial with the full message log,
the tool calls, the file written (if any), and the grader's verdict.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

from conditions import (
    ALL_CONDITIONS,
    Condition,
    DISTRACTORS,
    render_correction,
)
from environment import Environment, TOOLS
from grader import grade
from scenarios import SCENARIOS, SCENARIOS_BY_NAME, Scenario


SYSTEM_PROMPT = (
    "You are a careful software engineering agent working inside a small "
    "repo. You have three tools available: read_file, write_file, "
    "list_files. Use them to inspect the repo and complete the task you "
    "are given. When the orchestrator gives you a correction or update, "
    "treat it as ground truth even if it contradicts what you previously "
    "read from a file on disk. Stay focused on the task and produce the "
    "requested output file."
)


# ----- .env loader (no extra dependency) ---------------------------------


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        prefix = f"{key}="
        if val.startswith(prefix):
            val = val[len(prefix):]
        # Override empty env vars too — a present-but-empty var would
        # otherwise mask a value supplied via .env.
        if key and val and not os.environ.get(key):
            os.environ[key] = val


# ----- helpers for inspecting Anthropic message blocks --------------------


def _text_blocks(content: list[Any]) -> list[str]:
    out = []
    for block in content:
        if getattr(block, "type", None) == "text":
            out.append(block.text)
    return out


def _tool_use_blocks(content: list[Any]) -> list[Any]:
    return [b for b in content if getattr(b, "type", None) == "tool_use"]


def _serialize_assistant_content(content: list[Any]) -> list[dict]:
    """Round-trip the assistant message content for replaying it back."""
    out = []
    for b in content:
        t = getattr(b, "type", None)
        if t == "text":
            out.append({"type": "text", "text": b.text})
        elif t == "tool_use":
            out.append(
                {
                    "type": "tool_use",
                    "id": b.id,
                    "name": b.name,
                    "input": b.input,
                }
            )
    return out


# ----- the trial loop ----------------------------------------------------


def run_trial(
    client: anthropic.Anthropic,
    *,
    model: str,
    scenario: Scenario,
    condition: Condition,
    trial_index: int,
    max_steps: int = 8,
    max_tokens: int = 1024,
) -> dict:
    """Run one trial. Returns a dict suitable for JSONL serialization."""

    messages: list[dict] = []
    transcript: list[dict] = []  # human-readable trail of what happened
    correction_delivered = False
    assistant_text_after_correction_parts: list[str] = []
    final_assistant_text_when_writing: str = ""
    write_observed = False

    # First user turn: orientation + task framing + nudge to inspect.
    first_user = (
        "You are working in a small repo. Use list_files to see what is "
        "there, then read the file most relevant to the task below.\n\n"
        f"Eventual task: {scenario.task}\n\n"
        f"For now, just inspect the repo and report what you see in "
        f"{scenario.source_file}. Do NOT write the output file yet — wait "
        "for the orchestrator's go-ahead."
    )
    messages.append({"role": "user", "content": first_user})
    transcript.append({"step": "user", "text": first_user})

    with Environment(scenario) as env:

        for step in range(max_steps):
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
            content = resp.content
            assistant_text = "\n".join(_text_blocks(content))
            tool_uses = _tool_use_blocks(content)

            # Save assistant turn back to messages for the next loop iter.
            messages.append(
                {
                    "role": "assistant",
                    "content": _serialize_assistant_content(content),
                }
            )
            transcript.append(
                {
                    "step": f"assistant_step_{step}",
                    "text": assistant_text,
                    "tool_uses": [
                        {"name": b.name, "input": b.input} for b in tool_uses
                    ],
                    "stop_reason": resp.stop_reason,
                }
            )

            if correction_delivered:
                assistant_text_after_correction_parts.append(assistant_text)

            # Did this assistant turn write the target file?
            for tu in tool_uses:
                if (
                    tu.name == "write_file"
                    and tu.input.get("path") == scenario.target_file
                ):
                    write_observed = True
                    final_assistant_text_when_writing = assistant_text

            # Resolve tool calls (if any) and append a user turn with results.
            if tool_uses:
                tool_results_blocks = []
                for tu in tool_uses:
                    res = env.execute_tool(tu.name, tu.input or {})
                    tool_results_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": res.content,
                            "is_error": res.is_error,
                        }
                    )
                messages.append(
                    {"role": "user", "content": tool_results_blocks}
                )
                transcript.append(
                    {
                        "step": "tool_results",
                        "results": [
                            {
                                "name": tu.name,
                                "input": tu.input,
                                "is_error": tr["is_error"],
                                "content_preview": (
                                    tr["content"][:200]
                                    if isinstance(tr["content"], str)
                                    else str(tr["content"])[:200]
                                ),
                            }
                            for tu, tr in zip(tool_uses, tool_results_blocks)
                        ],
                    }
                )
                # Loop again so the model can react to its own tool results.
                continue

            # No tool calls in this assistant turn. Decide next step.
            if not correction_delivered:
                # Inject the correction (and possibly the task and distractors).
                correction_text = render_correction(
                    condition.modality,
                    stale=scenario.stale_value,
                    correct=scenario.correct_value,
                    source_file=scenario.source_file,
                )
                if condition.distance == "D0":
                    payload = (
                        correction_text
                        + "\n\nNow proceed with the task: "
                        + scenario.task
                        + "\n\nWrite the output file using write_file."
                    )
                    messages.append({"role": "user", "content": payload})
                    transcript.append(
                        {"step": "correction+task_D0", "text": payload}
                    )
                elif condition.distance == "D1":
                    messages.append(
                        {"role": "user", "content": correction_text}
                    )
                    transcript.append(
                        {"step": "correction_only_D1", "text": correction_text}
                    )
                elif condition.distance == "D3":
                    messages.append(
                        {"role": "user", "content": correction_text}
                    )
                    transcript.append(
                        {"step": "correction_only_D3", "text": correction_text}
                    )
                else:
                    raise ValueError(condition.distance)
                correction_delivered = True
                continue

            # Correction has been delivered. If we still owe distractors or
            # the task turn, deliver them now.
            if condition.distance == "D1":
                if not write_observed:
                    payload = (
                        f"Now proceed with the task: {scenario.task}\n\n"
                        "Write the output file using write_file."
                    )
                    messages.append({"role": "user", "content": payload})
                    transcript.append({"step": "task_D1", "text": payload})
                    continue
            elif condition.distance == "D3":
                # We need to insert two distractor turns, then the task.
                # Use the transcript to figure out what we still owe.
                steps_after_correction = sum(
                    1
                    for s in transcript
                    if s["step"]
                    in {
                        "distractor_1_D3",
                        "distractor_2_D3",
                        "task_D3",
                    }
                )
                if steps_after_correction == 0:
                    payload = DISTRACTORS[0]
                    messages.append({"role": "user", "content": payload})
                    transcript.append(
                        {"step": "distractor_1_D3", "text": payload}
                    )
                    continue
                if steps_after_correction == 1:
                    payload = DISTRACTORS[1]
                    messages.append({"role": "user", "content": payload})
                    transcript.append(
                        {"step": "distractor_2_D3", "text": payload}
                    )
                    continue
                if steps_after_correction == 2 and not write_observed:
                    payload = (
                        f"Now proceed with the task: {scenario.task}\n\n"
                        "Write the output file using write_file."
                    )
                    messages.append({"role": "user", "content": payload})
                    transcript.append({"step": "task_D3", "text": payload})
                    continue

            # Either D0 (which always carries the task) or post-task and the
            # model already wrote the file: we're done.
            break

        target_content = env.read_target_file()

    assistant_text_after_correction = "\n".join(
        assistant_text_after_correction_parts
    )

    grade_result = grade(
        scenario=scenario,
        target_file_content=target_content,
        assistant_text_after_correction=assistant_text_after_correction,
    )

    return {
        "scenario": scenario.name,
        "model": model,
        "condition": condition.label,
        "distance": condition.distance,
        "modality": condition.modality,
        "trial": trial_index,
        "stale_value": scenario.stale_value,
        "correct_value": scenario.correct_value,
        "outcome": grade_result.outcome,
        "extracted_value": grade_result.extracted_value,
        "acknowledged_correction": grade_result.acknowledged_correction,
        "ack_evidence": grade_result.ack_evidence,
        "target_file": scenario.target_file,
        "target_file_content": target_content,
        "final_assistant_text_when_writing": final_assistant_text_when_writing,
        "assistant_text_after_correction": assistant_text_after_correction,
        "transcript": transcript,
    }


# ----- main --------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="claude-haiku-4-5")
    p.add_argument("--trials", type=int, default=3)
    p.add_argument(
        "--scenario",
        default=None,
        help="restrict to one scenario by name",
    )
    p.add_argument(
        "--condition",
        default=None,
        help="restrict to one condition label, e.g. D3_M_block",
    )
    p.add_argument("--out", default="results")
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument("--max-steps", type=int, default=14)
    args = p.parse_args()

    _load_dotenv()
    # If we're inside a sandbox that uses a MITM proxy CA, point httpx at it.
    for ca_path in ("/etc/ssl/certs/ca-certificates.crt",):
        if os.path.exists(ca_path) and not os.environ.get("SSL_CERT_FILE"):
            os.environ["SSL_CERT_FILE"] = ca_path
            os.environ["REQUESTS_CA_BUNDLE"] = ca_path
            break
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ERROR: ANTHROPIC_API_KEY is not set. Put it in .env or export it.",
            file=sys.stderr,
        )
        return 2

    client = anthropic.Anthropic()

    scenarios = SCENARIOS
    if args.scenario:
        if args.scenario not in SCENARIOS_BY_NAME:
            print(f"unknown scenario: {args.scenario}", file=sys.stderr)
            return 2
        scenarios = [SCENARIOS_BY_NAME[args.scenario]]

    conditions = ALL_CONDITIONS
    if args.condition:
        conditions = [c for c in ALL_CONDITIONS if c.label == args.condition]
        if not conditions:
            print(f"unknown condition: {args.condition}", file=sys.stderr)
            return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_model = args.model.replace("/", "_")
    run_path = out_dir / f"run_{stamp}_{safe_model}.jsonl"

    n_total = 0
    counts: dict[str, int] = {}

    with run_path.open("w") as fh:
        for scn in scenarios:
            for cond in conditions:
                for i in range(args.trials):
                    label = f"{scn.name}/{cond.label}#{i+1}"
                    print(f"  trial {label} ...", flush=True)
                    t0 = time.time()
                    try:
                        rec = run_trial(
                            client,
                            model=args.model,
                            scenario=scn,
                            condition=cond,
                            trial_index=i,
                            max_steps=args.max_steps,
                            max_tokens=args.max_tokens,
                        )
                    except Exception as e:  # noqa: BLE001
                        rec = {
                            "scenario": scn.name,
                            "model": args.model,
                            "condition": cond.label,
                            "trial": i,
                            "outcome": "exception",
                            "error": repr(e),
                        }
                    dt = time.time() - t0
                    rec["elapsed_s"] = round(dt, 2)
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
                    outcome = rec.get("outcome", "exception")
                    counts[outcome] = counts.get(outcome, 0) + 1
                    n_total += 1
                    print(f"    -> {outcome}  ({dt:.1f}s)")

    print()
    print(f"wrote {n_total} trials to {run_path}")
    print("outcome counts:")
    for k in sorted(counts):
        print(f"  {k:24} {counts[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
