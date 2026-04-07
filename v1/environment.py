"""
The on-disk environment for one trial.

Each trial gets a fresh temp directory containing the scenario's starter
files. The model under test is given two tools — `read_file` and
`write_file` — and one safety rail (`list_files`). All paths are resolved
inside the trial's root and any attempt to escape the root is rejected.

This module is independent of any LLM provider. The runner is responsible
for taking the model's tool_use blocks, calling `Environment.execute_tool`,
and feeding the results back. That keeps the env easy to swap providers
on later (e.g. OpenAI) without touching trial logic.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scenarios import Scenario


# Tool schemas in the Anthropic Messages API tool format.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": (
            "Read a UTF-8 text file from the repo root. Use this to inspect "
            "the current state of files in the working directory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repo-relative path to the file to read.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Create or overwrite a UTF-8 text file in the repo root. "
            "Parent directories are created automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repo-relative path to the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List all files currently present in the repo root.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


@dataclass
class ToolResult:
    is_error: bool
    content: str


class Environment:
    """Sandbox for one trial.

    Use as a context manager so the temp directory is always cleaned up:

        with Environment(scenario) as env:
            ...
    """

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self._tmp: tempfile.TemporaryDirectory | None = None
        self.root: Path | None = None

    def __enter__(self) -> "Environment":
        self._tmp = tempfile.TemporaryDirectory(prefix="cor_trial_")
        self.root = Path(self._tmp.name)
        for rel, content in self.scenario.starter_files.items():
            target = self._safe_join(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
        self._tmp = None
        self.root = None

    # ---- safety ----------------------------------------------------------

    def _safe_join(self, rel: str) -> Path:
        if self.root is None:
            raise RuntimeError("Environment is not active")
        # Normalize and ensure the resolved path stays inside root.
        candidate = (self.root / rel).resolve()
        root_resolved = self.root.resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError as e:
            raise ValueError(f"path escapes repo root: {rel}") from e
        return candidate

    # ---- tool execution --------------------------------------------------

    def execute_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        try:
            if name == "read_file":
                return self._read_file(args.get("path", ""))
            if name == "write_file":
                return self._write_file(
                    args.get("path", ""),
                    args.get("content", ""),
                )
            if name == "list_files":
                return self._list_files()
            return ToolResult(True, f"unknown tool: {name}")
        except Exception as e:  # noqa: BLE001
            return ToolResult(True, f"tool error: {type(e).__name__}: {e}")

    def _read_file(self, rel: str) -> ToolResult:
        if not rel:
            return ToolResult(True, "missing 'path' argument")
        path = self._safe_join(rel)
        if not path.exists():
            return ToolResult(True, f"file not found: {rel}")
        if not path.is_file():
            return ToolResult(True, f"not a regular file: {rel}")
        return ToolResult(False, path.read_text())

    def _write_file(self, rel: str, content: str) -> ToolResult:
        if not rel:
            return ToolResult(True, "missing 'path' argument")
        path = self._safe_join(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return ToolResult(False, f"wrote {rel} ({len(content)} bytes)")

    def _list_files(self) -> ToolResult:
        if self.root is None:
            return ToolResult(True, "env not active")
        out = []
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for fn in filenames:
                full = Path(dirpath) / fn
                out.append(str(full.relative_to(self.root)))
        out.sort()
        return ToolResult(False, "\n".join(out) if out else "(empty)")

    # ---- post-trial introspection ---------------------------------------

    def read_target_file(self) -> str | None:
        """Return the contents of the scenario's target_file, or None."""
        if self.root is None:
            return None
        path = self._safe_join(self.scenario.target_file)
        if not path.exists() or not path.is_file():
            return None
        return path.read_text()


if __name__ == "__main__":
    # Smoke test
    from scenarios import SCENARIOS
    s = SCENARIOS[0]
    with Environment(s) as env:
        print("root:", env.root)
        print(env.execute_tool("list_files", {}).content)
        print("---")
        print(env.execute_tool("read_file", {"path": s.source_file}).content)
        env.execute_tool("write_file", {
            "path": s.target_file,
            "content": "current_version: 18.2.0\nhello\n",
        })
        print("---")
        print("target after write:")
        print(env.read_target_file())
