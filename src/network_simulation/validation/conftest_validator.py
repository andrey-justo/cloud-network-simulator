from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class ConftestValidator:
    """Evaluate compiled ARM JSON against the configured Rego policies."""

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("conftest")

    def validate(self, compiled_template: Path, policy_directory: Path) -> dict[str, object]:
        policy_files = sorted(policy_directory.glob("*.rego"))
        if not policy_files:
            return {
                "status": "unavailable",
                "error": f"No Rego policies found in {policy_directory}.",
            }
        if not self.executable:
            return {
                "status": "unavailable",
                "error": "Conftest was not found on PATH.",
            }

        completed = subprocess.run(
            [
                self.executable,
                "test",
                str(compiled_template),
                "--policy",
                str(policy_directory),
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "status": "passed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "policy_files": [str(path) for path in policy_files],
        }