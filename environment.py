"""
v2/v3 environment — scenario-driven tool-use harness.

Instantiated per-trial with a ScenarioSpec. The spec carries its own
tool names, tool schemas, stale/fresh reports, and consequence strings.
The environment exposes two behaviors to the runner:

  - dispatch a tool call to either the scenario's query tool (returning
    stale or fresh report based on `fresh_mode`) or the scenario's
    action tool (recording the call, returning the consequence string)
  - expose the FIRST action-tool call's argument to the grader
    (`first_action_value`)

Structural translation of the trading-system failure: a research-style
agent's tool result enters context as the stale value, the orchestrator
(or a re-call of the same tool) provides a corrected value, and the
model performs an irreversible action whose argument is graded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scenarios import ScenarioSpec


# Legacy export so older runner imports don't blow up. The active set of
# tools is now carried on each ScenarioSpec via spec.tool_schemas(variant).
TOOLS: list[dict[str, Any]] = []


@dataclass
class ToolResult:
    is_error: bool
    content: str


@dataclass
class ActionCall:
    value: Any


class Environment:
    """Stateful per-trial harness."""

    def __init__(self, scenario: ScenarioSpec) -> None:
        self.scenario = scenario
        self.fresh_mode = False
        self.query_calls = 0
        self.action_calls: list[ActionCall] = []

    # Runner flips this when entering the post-correction phase under the
    # "recompute" correction source. After flipping, the query tool
    # returns the fresh report.
    def enable_fresh_mode(self) -> None:
        self.fresh_mode = True

    def execute_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        spec = self.scenario
        try:
            if name == spec.query_tool_name:
                return self._query(args.get(spec.query_arg_name, ""))
            if name == spec.action_tool_name:
                return self._action(args.get(spec.action_arg_name))
            return ToolResult(True, f"unknown tool: {name}")
        except Exception as e:  # noqa: BLE001
            return ToolResult(True, f"tool error: {type(e).__name__}: {e}")

    # ---- tool implementations -------------------------------------------

    def _query(self, question: str) -> ToolResult:
        self.query_calls += 1
        body = (
            self.scenario.fresh_report
            if self.fresh_mode
            else self.scenario.stale_report
        )
        if question:
            body = f"# question: {question}\n\n{body}"
        return ToolResult(False, body)

    def _action(self, value: Any) -> ToolResult:
        spec = self.scenario
        if spec.value_kind == "integer":
            if not isinstance(value, int):
                try:
                    value = int(value)
                except Exception:
                    return ToolResult(
                        True,
                        f"{spec.action_arg_name} must be an integer; got {value!r}",
                    )
        else:
            if not isinstance(value, str):
                value = str(value) if value is not None else ""

        self.action_calls.append(ActionCall(value=value))

        if self._matches(value, spec.correct_value):
            return ToolResult(False, spec.consequence_for_correct)
        if self._matches(value, spec.stale_value):
            return ToolResult(True, spec.consequence_for_stale)
        return ToolResult(True, f"unknown {spec.action_arg_name} {value!r}; refusing")

    @staticmethod
    def _matches(a: Any, b: Any) -> bool:
        return str(a).strip() == str(b).strip()

    # ---- post-trial introspection ---------------------------------------

    @property
    def first_action_value(self) -> Any:
        return self.action_calls[0].value if self.action_calls else None

    # Back-compat shim — older code uses these names.
    @property
    def first_kill_pid(self) -> Any:
        return self.first_action_value

    @property
    def telemetry_calls(self) -> int:
        return self.query_calls

    @property
    def kill_calls(self) -> list[ActionCall]:
        return self.action_calls


if __name__ == "__main__":
    from scenarios import SCENARIOS

    for spec in SCENARIOS:
        print(f"=== {spec.name} ===")
        env = Environment(spec)
        print(env.execute_tool(spec.query_tool_name, {spec.query_arg_name: "status?"}).content[:220])
        print("...")
        env.enable_fresh_mode()
        print(env.execute_tool(spec.query_tool_name, {spec.query_arg_name: "re-check"}).content[:220])
        print("...")
        # Wrong value
        r = env.execute_tool(spec.action_tool_name, {spec.action_arg_name: spec.stale_value})
        print("stale ->", r.is_error, r.content[:120])
        # Correct value
        env2 = Environment(spec)
        r = env2.execute_tool(spec.action_tool_name, {spec.action_arg_name: spec.correct_value})
        print("correct ->", r.is_error, r.content[:120])
        print()
