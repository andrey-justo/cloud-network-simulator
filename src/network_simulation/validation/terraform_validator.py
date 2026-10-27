"""Offline Terraform validation using only harness-pinned official providers."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from network_simulation.scenario_targets import TARGETS
from network_simulation.validation.terraform_source import (
    parse_terraform,
    terraform_resources,
)
from network_simulation.validation.environment import isolated_environment


class TerraformValidator:
    def __init__(self, workspace: Path, executable: str | None = None) -> None:
        local = (
            workspace
            / ".tools"
            / "terraform"
            / ("terraform.exe" if os.name == "nt" else "terraform")
        )
        self.executable = (
            executable
            or shutil.which("terraform")
            or (str(local) if local.is_file() else None)
        )
        self._directories: dict[str, tempfile.TemporaryDirectory[str]] = {}
        self.tool_version: str | None = None

    def close(self) -> None:
        for directory in self._directories.values():
            directory.cleanup()
        self._directories.clear()

    def _environment(self, directory: Path) -> dict[str, str]:
        env = isolated_environment()
        env.update(
            TF_IN_AUTOMATION="1",
            TF_INPUT="0",
            CHECKPOINT_DISABLE="1",
            TF_CLI_CONFIG_FILE=str(directory / "terraform.rc"),
        )
        return env

    def _command(
        self, directory: Path, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        if not self.executable:
            raise RuntimeError(
                "Terraform CLI is unavailable; install it on PATH or in .tools\\terraform."
            )
        return subprocess.run(
            [self.executable, *arguments],
            cwd=directory,
            env=self._environment(directory),
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )

    @staticmethod
    def provider_configuration(target: str) -> str:
        definition = TARGETS[target]
        provider = definition["provider"]
        body = (
            'features {}\n  subscription_id = "00000000-0000-0000-0000-000000000000"'
            if provider == "azurerm"
            else 'region = "us-east-1"'
        )
        return f'terraform {{\n  required_providers {{\n    {provider} = {{ source = "hashicorp/{provider}", version = "{definition["version"]}" }}\n  }}\n}}\nprovider "{provider}" {{\n  {body}\n}}\n'

    def prepare(self, target: str) -> Path:
        if target in self._directories:
            return Path(self._directories[target].name)
        holder = tempfile.TemporaryDirectory(prefix=f"iac-{target}-")
        directory = Path(holder.name)
        try:
            (directory / "providers.tf").write_text(
                self.provider_configuration(target), encoding="utf-8"
            )
            (directory / "terraform.rc").write_text(
                "disable_checkpoint = true\n", encoding="utf-8"
            )
            initialized = self._command(
                directory, "init", "-backend=false", "-input=false", "-no-color"
            )
            if initialized.returncode:
                raise RuntimeError(
                    f"Terraform provider initialization failed for {target}: {initialized.stderr or initialized.stdout}"
                )
            version_result = self._command(directory, "version", "-json")
            version = json.loads(version_result.stdout).get("terraform_version")
            if version_result.returncode or not isinstance(version, str) or not version:
                raise RuntimeError("Terraform returned invalid version evidence.")
            self.tool_version = version
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            holder.cleanup()
            raise
        self._directories[target] = holder
        return directory

    def preflight(self, targets: list[str], *, initialize: bool = False) -> list[str]:
        errors = []
        if not self.executable:
            errors.append(
                "Terraform CLI is unavailable. Install on PATH or in .tools\\terraform before execution."
            )
        if importlib.util.find_spec("hcl2") is None:
            errors.append(
                "Terraform HCL parser is unavailable. Restore the project dependencies."
            )
        if not errors and initialize:
            for target in targets:
                try:
                    self.prepare(target)
                except (
                    OSError,
                    ValueError,
                    RuntimeError,
                    subprocess.SubprocessError,
                ) as error:
                    errors.append(str(error))
        return errors

    def validate(self, source: Path, target: str) -> dict[str, Any]:
        from lark.exceptions import LarkError

        try:
            document = parse_terraform(source.read_text(encoding="utf-8"))
            if any(
                document.get(key)
                for key in ("terraform", "provider", "variable", "locals", "output")
            ):
                raise ValueError(
                    "Return resource blocks only; the harness supplies pinned providers. Variables, locals and outputs are excluded from this literal/symbolic benchmark."
                )
            resources = terraform_resources(document)
            if not resources or any(
                not kind.startswith(TARGETS[target]["provider"] + "_")
                for kind, _ in resources
            ):
                raise ValueError(
                    "Use only resources from the selected official provider."
                )
        except (ValueError, TypeError, KeyError, LarkError) as error:
            return {"status": "failed", "diagnostics": [str(error)]}
        directory = self.prepare(target)
        (directory / "main.tf").write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )
        result = self._command(directory, "validate", "-json", "-no-color")
        try:
            report = json.loads(result.stdout)
        except ValueError as error:
            raise RuntimeError(
                f"Terraform returned invalid validation evidence: {result.stderr}"
            ) from error
        if type(report.get("valid")) is not bool or result.returncode not in (0, 1):
            raise RuntimeError(
                f"Terraform validation failed operationally: {result.stderr or result.stdout}"
            )
        if report["valid"] and result.returncode:
            raise RuntimeError(
                "Terraform returned contradictory validity and exit status."
            )
        if report["valid"]:
            (source.parent / "template.json").write_text(
                json.dumps(document, indent=2) + "\n", encoding="utf-8"
            )
        for filename in ("providers.tf", ".terraform.lock.hcl"):
            shutil.copyfile(directory / filename, source.parent / filename)
        return {
            **report,
            "status": "passed" if report["valid"] else "failed",
            "stderr": result.stderr,
            "terraform_version": self.tool_version,
            "scope": "terraform validate only; no plan, state, provider configuration, apply or cloud API evaluation",
        }
