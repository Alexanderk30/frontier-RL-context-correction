# Context Override Resistance

A small RL-style coding environment for measuring whether a frontier
coding agent will verbally acknowledge a correction and then act on
the stale tool result anyway.

Motivated by a real failure mode I hit in a multi-agent trading
pipeline: a research agent emitted a stale value, an orchestrator
issued a correction, the executor verbally restated the correction
and then placed the order against the stale value. This repo tries
to reproduce that pattern in a smaller, fully synthetic, easily
inspectable harness.

Status: scaffolding. Scenarios, conditions, runner, and grader to
follow in subsequent commits.

## Layout (planned)

- `scenarios.py` — task definitions
- `environment.py` — per-trial tool-use harness
- `conditions.py` — correction-source × distance grid
- `run_trials.py` — Anthropic Messages API tool-use loop
- `grader.py` — outcome bucketing
- `results/` — JSONL run outputs

## Setup

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
```
