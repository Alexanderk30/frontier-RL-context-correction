"""
Per-trial environment for v2's wrong_pid_to_kill scenario.

The harness controls which telemetry report the model sees by toggling
fresh_mode. Records every kill_process call so the grader can inspect
the FIRST one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scenarios import (
    CONSEQUENCE_FOR_CORRECT,
    CONSEQUENCE_FOR_STALE,
    CORRECT_PID,
    FRESH_REPORT,
    STALE_PID,
    STALE_REPORT,
)


@dataclass
class Environment:
    fresh_mode: bool = False
    telemetry_calls: list[str] = field(default_factory=list)
    kill_calls: list[int] = field(default_factory=list)

    def enable_fresh_mode(self) -> None:
        self.fresh_mode = True

    @property
    def first_kill_pid(self) -> int | None:
        return self.kill_calls[0] if self.kill_calls else None

    def execute_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "query_telemetry_agent":
            self.telemetry_calls.append(str(args.get("question", "")))
            return FRESH_REPORT if self.fresh_mode else STALE_REPORT
        if name == "kill_process":
            try:
                pid = int(args["pid"])
            except (KeyError, TypeError, ValueError):
                return "ERROR: pid argument missing or not an integer."
            self.kill_calls.append(pid)
            if pid == CORRECT_PID:
                return CONSEQUENCE_FOR_CORRECT
            if pid == STALE_PID:
                return CONSEQUENCE_FOR_STALE
            return f"ERROR: pid {pid} not found in process table."
        return f"ERROR: unknown tool {name!r}"
