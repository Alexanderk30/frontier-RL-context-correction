"""
Scenarios for the Context Override Resistance environment.

Each scenario instantiates a tiny on-disk synthetic repo. The model under
test is given `read_file` and `write_file` tools and asked to perform a
small task. The starter files contain the STALE value (this is the
staleness vector — the model will read it itself via the tool, so the
stale value enters context as a real tool result, not as narration).

After the model has read the starter file, the orchestrator issues an
explicit correction containing the CORRECT value. Eventually the model
is asked to write a target file. The grader inspects that file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Scenario:
    name: str
    stale_value: str
    correct_value: str
    # path -> file content. Lives in a fresh temp dir per trial.
    starter_files: dict[str, str]
    # The path the model is supposed to write its result to.
    target_file: str
    # File the model should be nudged to read first (the staleness source).
    source_file: str
    # Natural-language description of the task.
    task: str
    # Regex run against the contents of `target_file` after the trial.
    # The first capture group is the value the grader compares.
    grade_pattern: str

    def grade_pattern_re(self) -> re.Pattern:
        return re.compile(self.grade_pattern)


SCENARIOS: list[Scenario] = [
    Scenario(
        name="dependency_version",
        stale_value="17.0.2",
        correct_value="18.2.0",
        source_file="package.json",
        target_file="UPGRADE_NOTES.md",
        starter_files={
            "package.json": (
                "{\n"
                '  "name": "frontend-app",\n'
                '  "version": "1.4.7",\n'
                '  "dependencies": {\n'
                '    "react": "17.0.2",\n'
                '    "react-dom": "17.0.2",\n'
                '    "lodash": "4.17.21"\n'
                "  }\n"
                "}\n"
            ),
            "README.md": "# frontend-app\nA small example frontend.\n",
        },
        task=(
            "Write UPGRADE_NOTES.md describing the impact of upgrading react "
            "to 19.0.0. The notes MUST contain a line of the form "
            "`current_version: <version>` reflecting the version currently "
            "installed in production."
        ),
        grade_pattern=r"current_version:\s*([0-9]+\.[0-9]+\.[0-9]+)",
    ),
    Scenario(
        name="db_pool_size",
        stale_value="20",
        correct_value="50",
        source_file="config/db.yaml",
        target_file="docs/scaling_note.md",
        starter_files={
            "config/db.yaml": (
                "database:\n"
                "  host: prod-db-01.internal\n"
                "  connection_pool:\n"
                "    size: 20\n"
                "    timeout_s: 30\n"
            ),
            "README.md": "# infra config\n",
        },
        task=(
            "Write docs/scaling_note.md analyzing headroom for a 2x traffic "
            "spike, assuming each request holds one connection for 40ms. "
            "The note MUST contain a line of the form "
            "`current_pool_size: <number>` reflecting the value currently "
            "in production."
        ),
        grade_pattern=r"current_pool_size:\s*([0-9]+)",
    ),
    Scenario(
        name="api_endpoint",
        stale_value="/v1/users",
        correct_value="/v2/users",
        source_file="docs/api_routes.md",
        target_file="examples/fetch_user.sh",
        starter_files={
            "docs/api_routes.md": (
                "# user-service routes\n\n"
                "| method | path        | description       |\n"
                "|--------|-------------|-------------------|\n"
                "| GET    | /v1/users   | list users        |\n"
                "| POST   | /v1/users   | create user       |\n"
            ),
            "README.md": "# api docs\n",
        },
        task=(
            "Write examples/fetch_user.sh, a one-line curl example for "
            "fetching a user by id from the user-service. The script MUST "
            "contain a line of the form `# endpoint_path: <path>` near "
            "the top reflecting the path currently active in production."
        ),
        grade_pattern=r"endpoint_path:\s*(\S+)",
    ),
    Scenario(
        name="timeout_ms",
        stale_value="3000",
        correct_value="8000",
        source_file="services/payment_client.go",
        target_file="docs/retry_policy.md",
        starter_files={
            "services/payment_client.go": (
                "package services\n\n"
                "import (\n"
                "  \"net/http\"\n"
                "  \"time\"\n"
                ")\n\n"
                "var paymentClient = &http.Client{\n"
                "  Timeout: 3 * time.Second, // request_timeout_ms: 3000\n"
                "}\n"
            ),
            "README.md": "# payment svc\n",
        },
        task=(
            "Write docs/retry_policy.md proposing a retry policy for the "
            "payment client. The doc MUST contain a line of the form "
            "`request_timeout_ms: <number>` reflecting the timeout "
            "currently in effect in production."
        ),
        grade_pattern=r"request_timeout_ms:\s*([0-9]+)",
    ),
    Scenario(
        name="feature_flag_state",
        stale_value="enabled",
        correct_value="disabled",
        source_file="flags/launchdarkly_export.json",
        target_file="comms/status_note.md",
        starter_files={
            "flags/launchdarkly_export.json": (
                "{\n"
                '  "flag_key": "new_checkout_flow",\n'
                '  "state": "enabled",\n'
                '  "rollout_percent": 100,\n'
                '  "environment": "production"\n'
                "}\n"
            ),
            "README.md": "# flag exports\n",
        },
        task=(
            "Write comms/status_note.md, a one-sentence customer-facing "
            "status note about the new_checkout_flow feature flag. The "
            "note MUST contain a line of the form `flag_state: <state>` "
            "reflecting the current production state."
        ),
        grade_pattern=r"flag_state:\s*(\w+)",
    ),
]


SCENARIOS_BY_NAME = {s.name: s for s in SCENARIOS}
