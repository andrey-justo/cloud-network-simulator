from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import yaml

from network_simulation.configuration import POCConfig
from network_simulation.scenario_context import resolve_scenario_context
from network_simulation.validation.bicep_compiler import BicepCompiler
from network_simulation.validation.checkov_validator import CheckovValidator, is_checkov_available
from network_simulation.validation.conftest_validator import ConftestValidator


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, default=_json_default, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean_bicep_response(response: str) -> str:
    lines = response.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
    return "\n".join(lines).strip() + "\n"


class LiveExperimentRunner:
    """Run B1/T1 generation and preserve all inputs, outputs, and checks."""

    def __init__(
        self,
        *,
        workspace_dir: str | Path,
        config: POCConfig,
        output_directory: str | Path | None = None,
        llm_client: Callable[[str], str] | None = None,
        bicep_compiler: BicepCompiler | None = None,
        checkov_validator: Any | None = None,
        conftest_validator: ConftestValidator | None = None,
    ) -> None:
        self.workspace = Path(workspace_dir).resolve()
        self.config = config
        configured_output = output_directory or config.experiment.output_directory
        self.output_directory = Path(configured_output)
        if not self.output_directory.is_absolute():
            self.output_directory = self.workspace / self.output_directory
        self.output_directory = self.output_directory.resolve()
        self.llm_client = llm_client
        self.bicep_compiler = bicep_compiler or BicepCompiler()
        self.checkov_validator = checkov_validator
        self.conftest_validator = conftest_validator or ConftestValidator()

    def run(self, scenario_ids: list[str]) -> dict[str, Any]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"live-{run_id}-{uuid4().hex[:8]}"
        run_directory = self.output_directory / run_id
        run_directory.mkdir(parents=True, exist_ok=False)

        prompt_directory = run_directory / "prompts"
        prompt_directory.mkdir()
        prompt_values = {
            "b1": self.config.prompts.system_prompt_b1,
            "t1": self.config.prompts.system_prompt_t1,
            "iterative": self.config.prompts.system_prompt_iterative,
        }
        for name, prompt in prompt_values.items():
            (prompt_directory / f"{name}.md").write_text(prompt + "\n", encoding="utf-8")

        endpoint = urlsplit(self.config.llm.azure_endpoint or "")
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "experiment_id": run_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "live",
            "provider": self.config.llm.provider,
            "authentication_mode": self.config.llm.authentication_mode,
            "model": self.config.llm.model_name,
            "generation_settings": self.config.llm.generation_settings,
            "endpoint_host": endpoint.hostname,
            "endpoint_path": endpoint.path,
            "endpoint_api_version": parse_qs(endpoint.query).get(
                "api-version", [None]
            )[0],
            "scenario_ids": [scenario.upper() for scenario in scenario_ids],
            "output_directory": str(run_directory),
            "prompt_sha256": {
                name: _sha256(prompt) for name, prompt in prompt_values.items()
            },
            "tool_versions": self._tool_versions(),
            "status": "started",
            "results": {},
        }
        _write_json(run_directory / "manifest.json", manifest)

        missing_tools = self._preflight_errors()
        if missing_tools:
            manifest["status"] = "blocked_missing_validation_tools"
            manifest["preflight_errors"] = missing_tools
            for scenario_id in scenario_ids:
                scenario_key = scenario_id.upper()
                scenario_path = (
                    self.workspace / "scenarios" / "specs" / f"{scenario_key}.yml"
                )
                scenario_directory = run_directory / "scenarios" / scenario_key
                scenario_directory.mkdir(parents=True, exist_ok=True)
                specification_hash = None
                if scenario_path.is_file():
                    specification_text = scenario_path.read_text(encoding="utf-8")
                    (scenario_directory / "specification.yml").write_text(
                        specification_text,
                        encoding="utf-8",
                    )
                    specification_hash = _sha256(specification_text)
                manifest["results"][scenario_key] = {
                    "status": "blocked_before_generation",
                    "reason": "Required validators are unavailable.",
                    "specification_sha256": specification_hash,
                }
            _write_json(run_directory / "manifest.json", manifest)
            return manifest

        if self.llm_client is None:
            try:
                self.llm_client = self.config.llm.create_client()
            except Exception as error:
                manifest["status"] = "blocked_model_configuration"
                manifest["preflight_errors"] = [str(error)]
                _write_json(run_directory / "manifest.json", manifest)
                return manifest

        for scenario_id in scenario_ids:
            scenario_key = scenario_id.upper()
            manifest["results"][scenario_key] = self._run_scenario(
                scenario_key,
                run_directory,
                prompt_values,
            )
            _write_json(run_directory / "manifest.json", manifest)

        statuses = [item["status"] for item in manifest["results"].values()]
        manifest["status"] = (
            "completed_with_unverified_scenario_acceptance"
            if statuses and all(status == "automated_checks_passed" for status in statuses)
            else "completed_with_failures_or_incomplete_checks"
        )
        _write_json(run_directory / "manifest.json", manifest)
        return manifest

    def _preflight_errors(self) -> list[str]:
        errors: list[str] = []
        validation = self.config.validation
        if not any(
            (
                validation.validate_bicep_syntax,
                validation.run_checkov,
                validation.run_opa_policies,
            )
        ):
            errors.append("Enable at least one automated validator before running.")
        if validation.validate_bicep_syntax and not self.bicep_compiler.executable:
            errors.append("Bicep CLI is not available on PATH.")
        if validation.run_checkov and self.checkov_validator is None and not is_checkov_available():
            errors.append("Neither the Checkov CLI nor its Python package is available.")
        if (validation.run_checkov or validation.run_opa_policies) and not validation.validate_bicep_syntax:
            errors.append("Bicep compilation must be enabled for Checkov or OPA validation.")
        if validation.run_opa_policies:
            policy_dir = self.workspace / validation.opa_policies_dir
            if not list(policy_dir.glob("*.rego")):
                errors.append(f"No Rego policies found in {policy_dir}.")
            elif not self.conftest_validator.executable:
                errors.append("Conftest is not available on PATH.")
        return errors

    def _tool_versions(self) -> dict[str, str | None]:
        executables = {
            "bicep": self.bicep_compiler.executable,
            "checkov": None if self.checkov_validator else shutil.which("checkov"),
            "conftest": self.conftest_validator.executable,
        }
        versions: dict[str, str | None] = {}
        for tool, executable in executables.items():
            if tool == "checkov" and self.checkov_validator:
                versions[tool] = "injected"
                continue
            if tool == "checkov" and not executable:
                try:
                    versions[tool] = importlib.metadata.version("checkov")
                except importlib.metadata.PackageNotFoundError:
                    versions[tool] = None
                continue
            if not executable:
                versions[tool] = None
                continue
            try:
                result = subprocess.run(
                    [executable, "--version"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                version_output = (result.stdout or result.stderr).strip()
                versions[tool] = version_output.splitlines()[0] if version_output else "unknown"
            except (OSError, subprocess.TimeoutExpired):
                versions[tool] = "unavailable"
        return versions

    def _run_scenario(
        self,
        scenario_id: str,
        run_directory: Path,
        prompts: dict[str, str],
    ) -> dict[str, Any]:
        spec_path = self.workspace / "scenarios" / "specs" / f"{scenario_id}.yml"
        if not spec_path.is_file():
            return {"status": "failed_missing_scenario", "error": str(spec_path)}

        source_specs: dict[str, str] = {}

        def load_spec(key: str) -> dict[str, Any]:
            path = self.workspace / "scenarios" / "specs" / f"{key}.yml"
            source_specs[key] = path.read_text(encoding="utf-8")
            return yaml.safe_load(source_specs[key])

        try:
            scenario = resolve_scenario_context(scenario_id, load_spec)
        except (OSError, ValueError, yaml.YAMLError) as error:
            return {"status": "failed_invalid_scenario", "error": str(error)}
        scenario_directory = run_directory / "scenarios" / scenario_id
        scenario_directory.mkdir(parents=True, exist_ok=True)
        source_directory = scenario_directory / "sources"
        source_directory.mkdir(exist_ok=True)
        for key, text in source_specs.items():
            (source_directory / f"{key}.yml").write_text(text, encoding="utf-8")
        spec_text = yaml.safe_dump(scenario, sort_keys=False, allow_unicode=True)
        (scenario_directory / "specification.yml").write_text(spec_text, encoding="utf-8")
        spec_hash = _sha256(spec_text)

        conditions: dict[str, Any] = {}
        if self.config.experiment.run_b1:
            conditions["B1"] = self._run_condition(
                scenario_id,
                scenario,
                spec_text,
                spec_hash,
                scenario_directory / "B1",
                "B1",
                prompts,
            )
        if self.config.experiment.run_t1:
            conditions["T1"] = self._run_condition(
                scenario_id,
                scenario,
                spec_text,
                spec_hash,
                scenario_directory / "T1",
                "T1",
                prompts,
            )

        status = (
            "automated_checks_passed"
            if conditions and all(item.get("automated_checks_passed") for item in conditions.values())
            else "failed_or_incomplete"
        )
        return {
            "status": status,
            "name": scenario.get("name", scenario_id),
            "specification_sha256": spec_hash,
            "source_sha256": {key: _sha256(text) for key, text in source_specs.items()},
            "context_chain": scenario["context_chain"],
            "scenario_acceptance": "not_automated",
            "conditions": conditions,
        }

    def _run_condition(
        self,
        scenario_id: str,
        scenario: dict[str, Any],
        spec_text: str,
        spec_hash: str,
        condition_directory: Path,
        condition: str,
        prompts: dict[str, str],
    ) -> dict[str, Any]:
        condition_directory.mkdir(parents=True, exist_ok=True)
        max_iterations = (
            1
            if condition == "B1"
            else self.config.experiment.t1_max_iterations
        )
        iterations: list[dict[str, Any]] = []
        validation_feedback = ""
        latest_passed = False
        previous_template = ""

        for iteration_number in range(1, max_iterations + 1):
            iteration_directory = condition_directory / f"iteration-{iteration_number:02d}"
            iteration_directory.mkdir(parents=True, exist_ok=True)
            if iteration_number == 1:
                prompt_template = prompts["b1" if condition == "B1" else "t1"]
                prompt = f"{prompt_template}\n\nScenario specification (YAML):\n{spec_text}"
            else:
                prompt = (
                    prompts["iterative"].format(validation_failures=validation_feedback)
                    + "\n\nScenario specification (YAML):\n"
                    + spec_text
                    + "\n\nCurrent Bicep template:\n"
                    + previous_template
                    + "\nRevise it and return only the complete Bicep template."
                )
            (iteration_directory / "prompt.md").write_text(prompt + "\n", encoding="utf-8")
            iteration_started = time.perf_counter()
            try:
                response = self.llm_client(prompt)
                template = _clean_bicep_response(response)
            except Exception as error:
                error_message = str(error).replace(
                    self.config.llm.azure_api_key or "\0", "[REDACTED]"
                )
                result = {
                    "iteration": iteration_number,
                    "status": "generation_failed",
                    "error": error_message,
                    "elapsed_seconds": time.perf_counter() - iteration_started,
                }
                _write_json(iteration_directory / "result.json", result)
                iterations.append(result)
                break

            (iteration_directory / "response.txt").write_text(
                response,
                encoding="utf-8",
            )
            template_path = iteration_directory / "template.bicep"
            template_path.write_text(template, encoding="utf-8")
            generation = {
                "status": "generated",
                "provider": self.config.llm.provider,
                "model": self.config.llm.model_name,
                "condition": condition,
                "scenario_id": scenario_id,
                "scenario_sha256": spec_hash,
                "prompt_sha256": _sha256(prompt),
                "response_sha256": _sha256(response),
                "template_sha256": _sha256(template),
                "response_characters": len(response),
            }
            _write_json(iteration_directory / "generation.json", generation)

            validation = self.validate_candidate(template_path, scenario_id)
            automated_checks_passed = all(
                validation[name]["status"] in {"passed", "disabled"}
                for name in ("bicep", "checkov", "conftest")
            )
            validation["scenario_acceptance"] = {
                "status": "not_automated",
                "criteria_total": len(scenario.get("acceptance_criteria", [])),
            }
            _write_json(iteration_directory / "validation.json", validation)

            iteration_result = {
                "iteration": iteration_number,
                "status": "automated_checks_passed" if automated_checks_passed else "failed_or_incomplete",
                "automated_checks_passed": automated_checks_passed,
                "scenario_acceptance": "not_automated",
                "elapsed_seconds": time.perf_counter() - iteration_started,
                "template": str(template_path.relative_to(condition_directory)),
                "validation": validation,
            }
            _write_json(iteration_directory / "result.json", iteration_result)
            iterations.append(iteration_result)
            previous_template = template
            latest_passed = automated_checks_passed
            if condition == "B1" or latest_passed:
                break
            validation_feedback = json.dumps(validation, indent=2, default=_json_default)

        condition_result = {
            "condition": condition,
            "automated_checks_passed": latest_passed,
            "status": (
                "automated_checks_passed_scenario_acceptance_unverified"
                if latest_passed
                else "not_converged_or_incomplete"
            ),
            "iterations": iterations,
            "iterations_to_automated_pass": (
                next(
                    (
                        item["iteration"]
                        for item in iterations
                        if item.get("automated_checks_passed")
                    ),
                    None,
                )
            ),
            "scenario_acceptance": "not_automated",
        }
        _write_json(condition_directory / "result.json", condition_result)
        return condition_result

    def validate_candidate(self, template_path: Path, scenario_id: str, *, checkov_checks: list[str] | None = None, checkov_required_checks: list[str] | None = None) -> dict[str, Any]:
        validation: dict[str, Any] = {}
        compiled_path = template_path.parent / "template.json"
        if self.config.validation.validate_bicep_syntax:
            validation["bicep"] = self.bicep_compiler.validate(template_path, compiled_path)
        else:
            validation["bicep"] = {"status": "disabled"}

        if self.config.validation.run_checkov:
            if validation["bicep"]["status"] == "passed":
                try:
                    validation["checkov"] = self.validate_checkov(compiled_path,scenario_id,"arm",checks=checkov_checks,required_checks=checkov_required_checks)
                except Exception as error:
                    validation["checkov"] = {
                        "status": "unavailable_or_failed", "error": str(error),
                    }
            else:
                validation["checkov"] = {
                    "status": "not_run", "reason": "Bicep compilation did not pass.",
                }
        else:
            validation["checkov"] = {"status": "disabled"}

        if self.config.validation.run_opa_policies:
            if validation["bicep"]["status"] == "passed":
                validation["conftest"] = self.conftest_validator.validate(
                    compiled_path, self.workspace / self.config.validation.opa_policies_dir,
                )
            else:
                validation["conftest"] = {
                    "status": "not_run", "reason": "Bicep compilation did not pass.",
                }
        else:
            validation["conftest"] = {"status": "disabled"}
        return validation

    def validate_checkov(self, template_path: Path, scenario_id: str, framework: str, *, checks: list[str] | None = None, required_checks: list[str] | None = None) -> dict[str,Any]:
        checkov = self.checkov_validator or CheckovValidator(framework=framework,**({"checks":checks} if checks is not None else {}))
        report = checkov.validate_template(str(template_path),scenario_id=scenario_id)
        data = asdict(report) if is_dataclass(report) else dict(report)
        counts = {name:data.get(name) for name in ("passed","failed","skipped","total_checks")}
        counts["parsing_errors"] = data.get("parsing_errors",0)
        if any(type(value) is not int or value < 0 for value in counts.values()):
            raise ValueError("Checkov report has missing or invalid check counts.")
        if counts["total_checks"] != counts["passed"]+counts["failed"]+counts["skipped"]:
            raise ValueError("Checkov report has inconsistent check counts.")
        status = "failed" if counts["failed"] or counts["parsing_errors"] else "no_checks_executed" if not counts["passed"] else "passed"
        baseline_error = None
        if checks is not None:
            results = data.get("results")
            if not isinstance(results,list):
                raise ValueError("Scoped Checkov result details are missing.")
            executed = {item["check_id"] for item in results if item.get("result") in ("passed","failed")}
            missing = set(required_checks or []) - executed
            if counts["skipped"] or missing:
                baseline_error = f"Scoped baseline checks must execute without suppression. Skipped: {counts['skipped']}; missing required IDs: {', '.join(sorted(missing)) or 'none'}."
                status = "failed"
        return {**data,"status":status,"selected_check_ids":checks,"required_check_ids":required_checks,"baseline_error":baseline_error}