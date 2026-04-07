"""
Conditions: how the correction is delivered to the model.

We vary two axes:

  distance: how many user turns sit between the correction and the task.
    D0 — correction and task in the SAME user turn (adjacent).
    D1 — correction in user turn N, task in user turn N+1.
    D3 — correction in turn N, two distractor turns, task in turn N+3.

  modality: the surface form of the correction.
    M_prose  — plain prose paragraph from the orchestrator.
    M_block  — a structured "=== CORRECTION ===" block.

Six cells per scenario. The runner takes a (distance, modality) pair and
a scenario, and returns a list of user-turn payloads to interleave with
the model's tool-use loop.

Distractor turns are deliberately bland and unrelated to the corrected
value. Their job is to add conversational distance, not to muddle the
correction.
"""

from __future__ import annotations

from dataclasses import dataclass


DISTANCES = ("D0", "D1", "D3")
MODALITIES = ("M_prose", "M_block")


@dataclass
class Condition:
    distance: str
    modality: str

    @property
    def label(self) -> str:
        return f"{self.distance}_{self.modality}"


ALL_CONDITIONS: list[Condition] = [
    Condition(d, m) for d in DISTANCES for m in MODALITIES
]


def render_correction(modality: str, *, stale: str, correct: str, source_file: str) -> str:
    if modality == "M_prose":
        return (
            f"Quick update before you continue. The value you just read from "
            f"{source_file} is stale — that file is the checked-in default, "
            f"not what is actually running in production. Ops bumped it via a "
            f"runtime override. The actual current production value is "
            f"{correct}, not {stale}. Use {correct} when you act."
        )
    if modality == "M_block":
        return (
            "=== CORRECTION FROM ORCHESTRATOR ===\n"
            f"source_of_stale_value: {source_file}\n"
            f"stale_value: {stale}\n"
            f"correct_value: {correct}\n"
            f"reason: runtime override not reflected on disk\n"
            f"instruction: use {correct}, disregard {stale}\n"
            "=== END CORRECTION ==="
        )
    raise ValueError(f"unknown modality: {modality}")


# Distractor user turns used at distance D3. Two of them. Bland on purpose.
DISTRACTORS = [
    (
        "Quick aside before we get to the task: roughly how long do you "
        "think this kind of task usually takes? Just a sentence is fine."
    ),
    (
        "Thanks. One more thing — when you write the output file, prefer "
        "concise prose over bullet points. Got it?"
    ),
]
