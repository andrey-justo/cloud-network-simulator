from __future__ import annotations

import shutil
import subprocess
import os
from pathlib import Path


class BicepCompiler:
    """Compile a Bicep template to ARM JSON without deploying it."""

    def __init__(self, executable: str | None = None) -> None:
        if executable is not None:
            self.executable = executable or None
            return

        self.executable = (
            os.getenv("BICEP_CLI")
            or shutil.which("bicep")
            or self._find_winget_install()
            or self._find_azure_cli_install()
        )

    @staticmethod
    def _find_azure_cli_install() -> str | None:
        candidate = (
            Path.home()
            / ".azure"
            / "bin"
            / ("bicep.exe" if os.name == "nt" else "bicep")
        )
        return str(candidate) if candidate.is_file() else None

    @staticmethod
    def _find_winget_install() -> str | None:
        winget_package_root = (
            Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
        )
        candidates = sorted(
            winget_package_root.glob("Microsoft.Bicep_*/bicep.exe"),
            reverse=True,
        )
        return str(candidates[0]) if candidates else None

    def validate(self, source: Path, output: Path) -> dict[str, object]:
        if not self.executable:
            return {
                "status": "unavailable",
                "error": "Bicep CLI was not found on PATH.",
                "source": str(source),
            }

        completed = subprocess.run(
            [self.executable, "build", str(source), "--outfile", str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "status": "passed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "source": str(source),
            "compiled_template": str(output) if completed.returncode == 0 else None,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
