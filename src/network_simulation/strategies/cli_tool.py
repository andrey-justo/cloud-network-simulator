from __future__ import annotations

import os
import logging
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from .base import ExecutionStrategy

logger = logging.getLogger(__name__)


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

        command_args = [str(arg) for arg in args or []]
        normalized_shell = shell.lower()
        candidates = {
            "pwsh": ("pwsh", "powershell"),
            "powershell": ("powershell", "pwsh"),
            "bash": ("bash", "pwsh", "powershell"),
            "sh": ("sh", "bash", "pwsh", "powershell"),
        }.get(normalized_shell)
        if candidates is None:
            raise ValueError(f"Unsupported shell: {shell}")
        options = params or {}
        merged_env = os.environ.copy()
        merged_env.update(options.get("env") or {})
        selected_shell = next(
            ((name, path) for name in candidates if (path := shutil.which(name))),
            None,
        )
        resolved_command = shutil.which(command, path=merged_env.get("PATH"))
        if resolved_command is None and Path(command).is_file():
            resolved_command = command
        native_command = (
            resolved_command
            if resolved_command and (
                Path(resolved_command).suffix.lower() in (".exe", ".com")
                if os.name == "nt"
                else Path(resolved_command).suffix.lower() not in (".ps1", ".cmd", ".bat")
            )
            else None
        )
        if selected_shell is None and native_command is None:
            raise FileNotFoundError(f"No available shell for {shell}.")
        name, executable = selected_shell or ("", "")
        if native_command is not None:
            invocation = [native_command, *command_args]
        elif name in ("pwsh", "powershell"):
            def quote(value: str) -> str:
                return "'" + value.replace("'", "''") + "'"

            command_text = (
                "& " + " ".join(quote(value) for value in [command, *command_args])
                if command_args or Path(command).is_file()
                else command
            )
            invocation = [executable, "-NoProfile", "-NonInteractive", "-Command", command_text]
        else:
            command_text = shlex.join([command, *command_args]) if command_args else command
            invocation = [executable, "-c", command_text]
        try:
            completed = subprocess.run(
                invocation,
                cwd=options.get("cwd"),
                env=merged_env,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            logger.error("CLI execution failed: %s", error)
            completed = subprocess.CompletedProcess(invocation, 1, "", str(error))

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
