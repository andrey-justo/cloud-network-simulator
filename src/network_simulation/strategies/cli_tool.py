from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from typing import Any, Mapping, Sequence

from .base import ExecutionStrategy


class CLIToolStrategy(ExecutionStrategy):
    """Strategy for local CLI execution through bash or PowerShell."""

    def execute(
        self,
        prompt: str,
        *,
        command: str | None = None,
        args: Sequence[str] | None = None,
        shell: str = "bash",
        method: str | None = None,
        params: Mapping[str, Any] | None = None,
        endpoint: str | None = None,
        llm_client: Any | None = None,
    ) -> dict[str, Any]:
        if not command:
            raise ValueError("A CLI command is required when mode is CLI_TOOL.")

        command_args = list(args or [])
        normalized_shell = shell.lower()

        def build_powershell_commands() -> list[list[str]]:
            commands: list[list[str]] = []
            for executable in ("pwsh", "powershell"):
                if not shutil.which(executable):
                    continue
                if command_args:
                    command_text = " ".join([command, *[shlex.quote(str(arg)) for arg in command_args]])
                    commands.append([executable, "-NoProfile", "-Command", command_text])
                else:
                    commands.append([executable, "-NoProfile", "-Command", command])
            return commands

        def build_bash_commands() -> list[list[str]]:
            commands: list[list[str]] = []
            if shutil.which("bash"):
                if command_args:
                    command_text = " ".join([shlex.quote(command), *[shlex.quote(str(arg)) for arg in command_args]])
                    commands.append(["bash", "-lc", command_text])
                else:
                    commands.append(["bash", "-lc", command])
            return commands

        candidate_cmds: list[list[str]] = []
        if normalized_shell in {"pwsh", "powershell"}:
            candidate_cmds = build_powershell_commands()
        elif normalized_shell in {"bash", "sh"}:
            candidate_cmds = build_bash_commands() + build_powershell_commands()
        else:
            candidate_cmds = build_bash_commands() + build_powershell_commands()

        if not candidate_cmds:
            candidate_cmds = [[shell, *command_args]] if command_args else [[shell]]

        last_error: Exception | None = None
        completed: subprocess.CompletedProcess[str] | None = None
        selected_cmd: list[str] = candidate_cmds[0]

        for candidate in candidate_cmds:
            try:
                merged_env = os.environ.copy()
                completed = subprocess.run(
                    candidate,
                    cwd=None,
                    env=merged_env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                selected_cmd = candidate
                if completed.returncode == 0:
                    break
                last_error = RuntimeError(f"command exited with code {completed.returncode}")
            except FileNotFoundError as exc:  # pragma: no cover - shell fallback path
                last_error = exc
                continue

        if completed is None:
            completed = subprocess.CompletedProcess(selected_cmd, 1, "", str(last_error) if last_error else "")

        return {
            "mode": "cli_tool",
            "prompt": prompt,
            "command": command,
            "args": list(command_args),
            "shell": shell,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "status": "ok" if completed.returncode == 0 else "error",
        }


__all__ = ["CLIToolStrategy"]
