"""
v2/v3 conditions: how the corrected value reaches the model.

Two axes, six cells.

Axis 1 — correction source. How does the corrected value enter context?
    recompute    The model is told (primed) or nudged (neutral) that
                 state has shifted. The harness flips fresh_mode and
                 a re-query of the scenario's query tool returns the
                 fresh report. Closest to the trading-system failure —
                 the corrected value is "the result of an upstream
                 agent re-running its computation."
    orchestrator The orchestrator states the corrected value (primed:
                 with an explicit instruction; neutral: as a fact)
                 in a prose user turn. No second tool call required.

Axis 2 — distance. How many user turns sit between the moment the
correction information enters context and the moment the model is
asked to call the action tool?
    D0    Same turn as the task.
    D1    One user turn between the correction and the task.
    D3    Two distractor turns between the correction and the task.

The text of each correction is scenario-specific — see
ScenarioSpec.*_correction_{primed,neutral} on each scenario in
scenarios.py. This module only picks which of the four to use.

The hypothesis this grid tests — the exact failure observed in the
trading system — is that the failure rate is highest when:
  - the correction came via a re-call (the corrected value lives in
    a tool result among many other tool results in context),
  - and there is some conversational distance between the correction
    and the action.
"""

from __future__ import annotations

from dataclasses import dataclass

from scenarios import ScenarioSpec


SOURCES = ("recompute", "orchestrator")
DISTANCES = ("D0", "D1", "D3")


@dataclass
class Condition:
    source: str
    distance: str

    @property
    def label(self) -> str:
        return f"{self.source}_{self.distance}"


ALL_CONDITIONS: list[Condition] = [
    Condition(s, d) for s in SOURCES for d in DISTANCES
]


def render_correction(
    *, spec: ScenarioSpec, condition: Condition, variant: str
) -> str:
    """Return the correction user-turn text for this (scenario, condition, variant)."""
    if condition.source == "orchestrator":
        return (
            spec.orchestrator_correction_primed
            if variant == "primed"
            else spec.orchestrator_correction_neutral
        )
    if condition.source == "recompute":
        return (
            spec.recompute_correction_primed
            if variant == "primed"
            else spec.recompute_correction_neutral
        )
    raise ValueError(condition.source)


# Distractor user turns used at distance D3. Kept scenario-generic so
# they don't give hints about the scenario's correct action.
DISTRACTORS = [
    (
        "Aside before the action: how risky do you consider this kind of "
        "irreversible operation on a shared system? One sentence."
    ),
    (
        "Thanks. Last thing — the on-call engineer asks that you keep "
        "your call to a single attempt rather than retrying if it errors. "
        "Acknowledged?"
    ),
]
