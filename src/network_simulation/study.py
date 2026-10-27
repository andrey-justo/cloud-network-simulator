"""Budget-controlled paired study; held-out checks never enter repair prompts."""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import yaml

from network_simulation.configuration import POCConfig
from network_simulation.live_experiment import (
    LiveExperimentRunner,
    _clean_bicep_response,
    _sha256,
    _write_json,
)
from network_simulation.scenario_context import resolve_scenario_context, render_requirements
from network_simulation.usage_accounting import call_usage, workflow_usage
from network_simulation.study_acceptance import evaluate_structure, scenario_contract
from network_simulation.study_cloud import AzureStudyBackend
from network_simulation.study_state import execution_lock, read_checkpoint, save_checkpoint
from network_simulation.scenario_targets import TARGETS, scenario_variants
from network_simulation.validation.terraform_validator import TerraformValidator
from network_simulation.validation.checkov_validator import is_checkov_available

ARMS = ("one_shot", "blind_refinement", "tool_feedback")
COMMON_PROMPT = """Generate a complete resource-group-scoped Azure Bicep template.
Implement the supplied high-level scenario, including its security and connectivity requirements.
Return only Bicep, without fences or explanatory prose. Do not omit required
resources to reduce policy findings. Choose a suitable architecture, resource names,
addressing and resource relationships from the stated requirements.
Do not create runtime probe VMs: those belong to the independent test harness.
"""


def _family(scenario_id: str) -> str:
    if scenario_id in ("NET-02", "NET-03", "NET-08", "NET-10"):
        return "three-tier"
    if scenario_id in ("NET-06", "NET-07", "NET-09"):
        return "hub-spoke"
    if scenario_id in ("NET-04", "NET-05"):
        return "egress-routing"
    return "basic"


def summarize_trials(
    trials: list[dict[str, Any]], *, seed: int, samples: int
) -> dict[str, Any]:
    """Descriptive estimates and family-clustered paired bootstrap intervals."""
    if any("target" in record for record in trials):
        return {
            "inference": "Descriptive target-stratified results; never pool clouds or IaC tools as independent repetitions.",
            "targets": {
                target: summarize_trials(
                    [{key:value for key,value in record.items() if key != "target"} for record in trials if record.get("target","azure-bicep")==target],
                    seed=seed,samples=samples,
                )
                for target in sorted({record.get("target","azure-bicep") for record in trials})
            },
        }
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trial in trials:
        by_model[trial["model"]].append(trial)
    result: dict[str, Any] = {
        "inference": "Exploratory estimates, not significance tests or confirmed hypotheses.",
        "models": {},
    }
    rng = random.Random(seed)
    for model, records in by_model.items():
        arms: dict[str, Any] = {}
        for arm in ARMS:
            values = [record["conditions"][arm] for record in records]
            costs = [item["cost_usd"] for item in values]
            assessed = [item for item in values if item["accepted"] is not None]
            structural = [item for item in values if item["structural_accepted"] is not None]
            arms[arm] = {
                "trials": len(values),
                "accepted": sum(item["accepted"] for item in assessed) if assessed else None,
                "acceptance_assessed": len(assessed),
                "acceptance_unassessed": len(values) - len(assessed),
                "acceptance_rate": sum(item["accepted"] for item in assessed) / len(assessed) if assessed else None,
                "structural_acceptance_rate": sum(
                    item["structural_accepted"] for item in structural
                )
                / len(structural) if structural else None,
                "visible_validation_pass_rate": sum(item["visible_checks_passed"] for item in values) / len(values),
                "usage": workflow_usage(values),
                "nonconverged": sum(
                    not item["visible_checks_passed"] for item in values
                ),
                "generation_failed": sum(item["generation_failed"] for item in values),
                "mean_elapsed_seconds_all_trials": sum(
                    item["elapsed_seconds"] for item in values
                )
                / len(values),
                "mean_cost_usd_all_trials": sum(costs) / len(costs)
                if all(cost is not None for cost in costs)
                else None,
                "unknown_cost_trials": sum(cost is None for cost in costs),
                "mean_elapsed_seconds_accepted_only": (
                    sum(item["elapsed_seconds"] for item in values if item["accepted"])
                    / sum(item["accepted"] is True for item in values)
                    if any(item["accepted"] for item in values)
                    else None
                ),
            }
        comparisons = {}
        for control in ("one_shot", "blind_refinement"):
            if any(record["conditions"][arm]["accepted"] is None for record in records for arm in ("tool_feedback", control)):
                comparisons[f"tool_feedback_minus_{control}"] = {
                    "status": "not_assessed", "paired_risk_difference": None,
                    "family_cluster_bootstrap_95_interval": None,
                    "reason": "Requirement satisfaction awaits independent human review.",
                }
                continue
            differences: dict[str, list[int]] = defaultdict(list)
            for record in records:
                differences[record["family"]].append(
                    int(record["conditions"]["tool_feedback"]["accepted"])
                    - int(record["conditions"][control]["accepted"])
                )
            flattened = [value for group in differences.values() for value in group]
            interval = None
            if len(differences) >= 2:
                groups = list(differences.values())
                estimates = []
                for _ in range(samples):
                    selected = [
                        value
                        for group in rng.choices(groups, k=len(groups))
                        for value in group
                    ]
                    estimates.append(sum(selected) / len(selected))
                estimates.sort()
                interval = [
                    estimates[int(0.025 * (samples - 1))],
                    estimates[int(0.975 * (samples - 1))],
                ]
            comparisons[f"tool_feedback_minus_{control}"] = {
                "paired_risk_difference": sum(flattened) / len(flattened),
                "family_cluster_bootstrap_95_interval": interval,
                "independent_families": len(differences),
                "interval_limitation": "Few families yield unstable intervals; absent with fewer than two.",
            }
        result["models"][model] = {
            "conditions": arms,
            "paired_comparisons": comparisons,
        }
    return result


class ControlledStudyRunner:
    def __init__(
        self,
        *,
        workspace_dir: str | Path,
        config: POCConfig,
        llm_clients: dict[str, Callable[[str], str]] | None = None,
        bicep_compiler: Any = None,
        checkov_validator: Any = None,
        conftest_validator: Any = None,
        cloud_backend: Any = None,
        terraform_validator: Any = None,
    ) -> None:
        self.workspace = Path(workspace_dir).resolve()
        self.config = config
        self.clients = dict(llm_clients or {})
        self.validator = LiveExperimentRunner(
            workspace_dir=self.workspace,
            config=config,
            bicep_compiler=bicep_compiler,
            checkov_validator=checkov_validator,
            conftest_validator=conftest_validator,
        )
        self.cloud = cloud_backend or AzureStudyBackend(config.cloud)
        self.call_ledger: list[dict[str, Any]] = []
        self.parameters: dict[str, Any] = {}
        self.scenario_parameters: dict[str, dict[str, Any]] = {}
        self.terraform = terraform_validator or TerraformValidator(self.workspace)

    def plan(self, scenario_ids: list[str]) -> dict[str, Any]:
        self.config.study.validate()
        if self.config.study.assessment_mode == "human_review" and self.config.cloud.enabled:
            raise ValueError("Human-review studies are static-only; cloud deployment is not permitted.")
        self.parameters = {}
        self.scenario_parameters = {}
        if self.config.cloud.parameters_file:
            raw_parameters = json.loads(
                Path(self.config.cloud.parameters_file).read_text(encoding="utf-8")
            )
            if not isinstance(raw_parameters, dict):
                raise ValueError("Deployment parameters must be a JSON object.")
            if "scenarios" in raw_parameters:
                if set(raw_parameters) != {"scenarios"} or not isinstance(
                    raw_parameters["scenarios"], dict
                ):
                    raise ValueError("Scenario parameters cannot mix schemas.")
                for key, values in raw_parameters["scenarios"].items():
                    if (
                        key not in {f"NET-{number:02}" for number in range(1, 11)}
                        or not isinstance(values, dict)
                        or not isinstance(values.get("parameters", values), dict)
                    ):
                        raise ValueError("Invalid scenario parameter object.")
                    self.scenario_parameters[key] = values.get("parameters", values)
            else:
                self.parameters = raw_parameters.get("parameters", raw_parameters)
                if not isinstance(self.parameters, dict):
                    raise ValueError("Deployment parameters must be a JSON object.")
        self.parameters = {**self.parameters, "studySuffix": "local"}
        if not scenario_ids or any(not isinstance(key, str) for key in scenario_ids):
            raise ValueError("Select at least one scenario ID.")
        keys = [key.upper() for key in scenario_ids]
        if len(set(keys)) != len(keys):
            raise ValueError("Scenario IDs must not be duplicated.")
        if any(re.fullmatch(r"NET-\d{2}", key) is None for key in keys):
            raise ValueError("Scenario IDs must identify NET-XX YAML specifications.")
        models = self.config.study.models or [self.config.llm.model_name]
        if self.config.llm.provider not in ("azure_responses", "copilot"):
            raise ValueError(f"Unsupported LLM provider: {self.config.llm.provider}")
        if self.config.llm.provider == "azure_responses" and any(
            model not in self.config.llm.available_models for model in models
        ):
            raise ValueError(
                "All study models must be supported by the configured provider."
            )
        scenarios = {}
        skipped_variants = []
        for key in keys:
            sources: dict[str, str] = {}

            def load(parent: str, sources: dict[str, str] = sources) -> dict[str, Any]:
                path = self.workspace / "scenarios" / "specs" / f"{parent}.yml"
                sources[parent] = path.read_text(encoding="utf-8")
                return yaml.safe_load(sources[parent])

            resolved = resolve_scenario_context(key, load)
            if "supported_targets" in resolved:
                if self.config.cloud.enabled:
                    raise ValueError("High-level target scenarios support static-only validation.")
                variants, skipped = scenario_variants(key, resolved, sources, self.config.study.targets)
                scenarios.update(variants)
                skipped_variants.extend(skipped)
                continue
            if "azure-bicep" not in self.config.study.targets:
                raise ValueError("Legacy NET-01 through NET-10 specifications require azure-bicep.")
            contract = {
                "version": "human-review-v1", "parameters": {"studySuffix": {}},
                "runtime_checks": [], "scope": "Human requirement assessment is pending.",
            } if self.config.study.assessment_mode == "human_review" else scenario_contract(key)
            supplied = self.scenario_parameters.get(key, self.parameters)
            unknown = supplied.keys() - contract["parameters"].keys()
            if unknown:
                raise ValueError(
                    f"{key}: unknown deployment parameter names: {', '.join(sorted(unknown))}"
                )
            scenarios[key] = {
                "specification": resolved,
                "sources": sources,
                "contract": contract,
                "family": _family(key),
                "specification_sha256": _sha256(
                    yaml.safe_dump(resolved, sort_keys=True)
                ),
            }
            skipped_variants.extend(
                {"intent":key,"target":target,"reason":"NET-01 through NET-10 retain their Azure/Bicep scope; NET-11 through NET-30 declare supported targets in YAML."}
                for target in self.config.study.targets if target != "azure-bicep"
            )
        if not scenarios:
            raise ValueError("No supported scenario/target variants were selected.")
        terraform_targets = {scenario["target"] for scenario in scenarios.values() if scenario.get("target","azure-bicep") != "azure-bicep"}
        if terraform_targets and (not self.config.validation.validate_terraform_syntax or self.config.validation.run_opa_policies):
            raise ValueError("Terraform requires validate_terraform_syntax: true and opa: false. Existing ARM Rego policies cannot validate Terraform.")
        for scenario in scenarios.values():
            if "target" in scenario:
                scenario["specification_sha256"] = _sha256(yaml.safe_dump(scenario["specification"],sort_keys=True))
        rng = random.Random(self.config.study.random_seed)
        endpoint = urlsplit(self.config.llm.azure_endpoint or "")
        jobs = [
            {"scenario_id": key, "model": model, "repetition": repetition,
             **({"target":scenarios[key]["target"],"intent":scenarios[key]["intent"]} if "target" in scenarios[key] else {})}
            for model in models
            for key in scenarios
            for repetition in range(1, self.config.study.repetitions + 1)
        ]
        rng.shuffle(jobs)
        for job in jobs:
            job["arm_order"] = rng.sample(list(ARMS), k=len(ARMS))
        return {
            "schema_version": 1,
            "mode": "controlled_study",
            "prompt_protocol": "human-readable-requirements-v2",
            "execution_blockers": [
                "Independent requirements-based acceptance is not implemented for the new high-level specs. "
                "Paid study execution is blocked; the removed exact-resource oracle must not score these scenarios."
            ] if any("target" in scenario for scenario in scenarios.values()) and self.config.study.assessment_mode != "human_review" else [],
            "models": models,
            "requested_scenarios":keys,
            "skipped_variants":skipped_variants,
            "target_prompts": {target:self._target_prompt(target) for target in sorted({scenario.get("target","azure-bicep") for scenario in scenarios.values()})},
            "target_implementation_sha256": {
                filename.name:_sha256((Path(__file__).parent / filename).read_text(encoding="utf-8"))
                for filename in (Path("scenario_targets.py"),Path("scenario_context.py"),Path("usage_accounting.py"),Path("live_experiment.py"),Path("validation") / "terraform_source.py",Path("validation") / "terraform_validator.py",Path("validation") / "checkov_validator.py",Path("validation") / "environment.py")
            },
            "provider": self.config.llm.provider,
            "authentication_mode": self.config.llm.authentication_mode,
            "endpoint_host": endpoint.hostname,
            "endpoint_path": endpoint.path,
            "endpoint_api_version": parse_qs(endpoint.query).get("api-version", [None])[
                0
            ],
            "study": asdict(self.config.study),
            "cloud": asdict(self.config.cloud),
            "validation": asdict(self.config.validation),
            "generation_settings": self.config.llm.generation_settings,
            "common_prompt": COMMON_PROMPT,
            "common_prompt_sha256": _sha256(COMMON_PROMPT),
            "acceptance_implementation_sha256": _sha256(
                Path(__file__)
                .with_name("study_acceptance.py")
                .read_text(encoding="utf-8")
            ),
            "runner_implementation_sha256": _sha256(Path(__file__).read_text(encoding="utf-8")),
            "scenarios": scenarios,
            "schedule": jobs,
            "maximum_physical_model_calls": len(jobs)
            * (1 + 2 * (self.config.study.max_iterations - 1))
            if self.config.llm.provider != "copilot" else None,
            "maximum_generation_requests": len(jobs)
            * (1 + 2 * (self.config.study.max_iterations - 1)),
            "model_call_accounting": "Copilot SDK invocations; backend retries may add inference calls."
            if self.config.llm.provider == "copilot" else "Direct Responses API requests.",
            "maximum_cloud_deployments": len(jobs) * len(ARMS)
            if self.config.cloud.enabled
            else 0,
            "primary_outcome": "Compilation and visible policy outcomes; requirement satisfaction is unassessed pending human review."
            if self.config.study.assessment_mode == "human_review"
            else "High-level requirement acceptance is not implemented; execution blocked."
            if any("target" in scenario for scenario in scenarios.values())
            else "final full acceptance within budget"
            if self.config.cloud.enabled
            else "final finite structural acceptance within budget (runtime unverified)",
            "stopping_rule": "Stop each arm on visible-validator pass, generation failure, or K attempts; never stop on held-out acceptance.",
            "exclusions": "No post-generation trial exclusions. Operational failures remain in the denominator.",
            "shared_initial_cost": "Each workflow includes the common candidate cost; physical ledger counts it once.",
            "cost_basis": "Copilot allowance/credits; token prices are not Copilot invoices."
            if self.config.llm.provider == "copilot" else "Nominal model-token cost estimates from user rates, not invoices. Azure resource costs and caching discounts are not inferred.",
            "parameter_overrides": {
                "studySuffix": "local for structural evaluation; unique per cloud deployment"
            },
            "paid_execution": False,
            "cloud_binding_errors": self._cloud_binding_errors(scenarios),
        }

    def _cloud_binding_errors(self, scenarios: dict[str, Any]) -> list[str]:
        if not self.config.cloud.enabled or not isinstance(
            self.cloud, AzureStudyBackend
        ):
            return []
        errors = []
        try:
            if not self.config.cloud.runtime_bindings_file:
                raise ValueError("cloud.runtime_bindings_file is required.")
            raw = json.loads(
                Path(self.config.cloud.runtime_bindings_file).read_text(
                    encoding="utf-8"
                )
            )
            if not isinstance(raw, dict):
                raise TypeError(
                    "Runtime bindings must be a scenario-keyed JSON object."
                )
        except (OSError, ValueError, TypeError) as error:
            return [f"Runtime bindings: {error}"]
        for key, scenario in scenarios.items():
            supplied = self.scenario_parameters.get(key, self.parameters)
            for name, declaration in scenario["contract"]["parameters"].items():
                if "defaultValue" not in declaration and name not in supplied:
                    errors.append(f"{key}: missing required cloud parameter {name}.")
            binding = raw.get(key)
            if not isinstance(binding, dict):
                errors.append(f"{key}: missing runtime bindings.")
                continue
            for check in scenario["contract"]["runtime_checks"]:
                required = (
                    (("destination", "service_resources"),)
                    if check["kind"] == "public_access_disabled"
                    else (
                        ("source", "sources"),
                        ("destination", "destinations"),
                    )
                )
                for field, section in required:
                    values = binding.get(section)
                    if not isinstance(values, dict) or check[field] not in values:
                        errors.append(
                            f"{key}/{check['id']}: missing {section}.{check[field]}."
                        )
                dns = binding.get("dns_private_addresses", {})
                if check["kind"] == "dns_private" and (
                    not isinstance(dns, dict) or check["destination"] not in dns
                ):
                    errors.append(
                        f"{key}/{check['id']}: missing private DNS address evidence."
                    )
                if check["kind"] == "egress_ip" and not binding.get(
                    "expected_egress_ip"
                ):
                    errors.append(
                        f"{key}/{check['id']}: missing expected egress IP evidence."
                    )
                routes = binding.get("route_destinations", {})
                if check["kind"] == "route" and (
                    not isinstance(routes, dict) or check["destination"] not in routes
                ):
                    errors.append(f"{key}/{check['id']}: missing next-hop evidence.")
        return errors

    def run(
        self, scenario_ids: list[str], *, allow_browser_auth: bool = False,
        resume_from: Path | None = None,
        on_started: Callable[[Path], None] | None = None,
        rerun_of: str | None = None,
    ) -> dict[str, Any]:
        plan = self.plan(scenario_ids)
        if plan["execution_blockers"]:
            raise ValueError(" ".join(plan["execution_blockers"]))
        root = Path(self.config.experiment.output_directory)
        if not root.is_absolute():
            root = self.workspace / root
        directory = resume_from.resolve() if resume_from else (
            root / f"study-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        ).resolve()
        if resume_from:
            if self.config.cloud.enabled:
                raise ValueError("Resume is supported only for static studies.")
            read_checkpoint(directory)
        else:
            directory.mkdir(parents=True, exist_ok=False)
        with execution_lock(directory):
            try:
                return self._run_locked(
                    scenario_ids, plan, directory, allow_browser_auth=allow_browser_auth,
                    resume=resume_from is not None, on_started=on_started, rerun_of=rerun_of,
                )
            finally:
                self.terraform.close()

    def _run_locked(
        self, scenario_ids: list[str], plan: dict[str, Any], directory: Path, *,
        allow_browser_auth: bool, resume: bool,
        on_started: Callable[[Path], None] | None, rerun_of: str | None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        if resume:
            checkpoint = read_checkpoint(directory)
            manifest = checkpoint["manifest"]
            if Path(manifest["output_directory"]).resolve() != directory:
                raise ValueError("Resume requires the original execution location; use a full rerun for moved results.")
            for field, value in plan.items():
                if field not in {"paid_execution", "maximum_generation_requests", "maximum_physical_model_calls"} and manifest.get(field) != value:
                    raise ValueError(f"Resume rejected: frozen study field changed: {field}. Use a full rerun.")
            if manifest["status"] in ("completed", "completed_with_operational_failures"):
                return manifest
            self.call_ledger = checkpoint["calls"]
            history = manifest.setdefault("resume_history", [])
            abandoned = []
            unknown = 0
            recorded_archives = {
                archive for item in history for archive in item["archived_partial_trials"]
            }
            for index, job in enumerate(plan["schedule"], 1):
                if index <= len(manifest["trials"]):
                    continue
                partial = directory / f"trial-{index:05d}"
                archives_root = directory / "interrupted-attempts"
                if partial.exists():
                    if not partial.resolve().is_relative_to(directory):
                        raise ValueError("Partial trial resolves outside its execution directory.")
                    archive = archives_root / f"{partial.name}-{uuid4().hex[:8]}"
                    archive.parent.mkdir(exist_ok=True)
                    # Archive before retrying; never edit or reuse an unfinished trajectory.
                    partial.rename(archive)
                # Also recover a rename interrupted before its checkpoint was committed.
                for archive in sorted(archives_root.glob(f"{partial.name}-*")):
                    if str(archive) in recorded_archives:
                        continue
                    abandoned.append(str(archive))
                    for prompt in sorted(archive.rglob("prompt.txt")):
                        generation = prompt.with_name("generation.json")
                        if generation.is_file():
                            record = json.loads(generation.read_text(encoding="utf-8"))
                            if not isinstance(record, dict) or record.get("model") != job["model"] or record.get("status") not in ("generated", "generation_failed"):
                                raise ValueError("Invalid archived generation evidence.")
                            record["directory"] = str(prompt.parent)
                            record["excluded_from_completed_trials"] = True
                            self.call_ledger.append(record)
                        else:
                            unknown += 1
            history.append({
                "resumed_at_utc": datetime.now(UTC).isoformat(),
                "completed_trials_preserved": len(manifest["trials"]),
                "archived_partial_trials": abandoned,
                "unknown_interrupted_requests": unknown,
            })
            manifest["unknown_interrupted_requests"] = sum(
                item["unknown_interrupted_requests"] for item in history
            )
            manifest["maximum_generation_requests"] = plan["maximum_generation_requests"] + sum(
                call.get("excluded_from_completed_trials", False) for call in self.call_ledger
            ) + manifest["unknown_interrupted_requests"]
            manifest.pop("preflight_errors", None)
            manifest.pop("error", None)
        else:
            self.call_ledger = []
            manifest = {
                **plan, "output_directory": str(directory), "status": "started",
                "created_at_utc": datetime.now(UTC).isoformat(), "trials": [],
                "tool_versions": self.validator._tool_versions(),
            }
            if rerun_of:
                manifest["rerun_of"] = rerun_of
            self.config.save_yaml(str(directory / "config.yaml"))
        manifest.update(status="started", runner_pid=os.getpid())
        manifest["elapsed_seconds_excludes_uncheckpointed_interruptions"] = resume
        manifest["generation_requests"] = len(self.call_ledger)
        save_checkpoint(directory, manifest, self.call_ledger)
        if on_started:
            on_started(directory)
        targets = {scenario.get("target","azure-bicep") for scenario in plan["scenarios"].values()}
        errors = self.validator._preflight_errors() if "azure-bicep" in targets else []
        tf_targets = sorted(targets - {"azure-bicep"})
        if tf_targets:
            errors.extend(self.terraform.preflight(tf_targets,initialize=True))
            manifest["tool_versions"]["terraform"] = getattr(self.terraform,"tool_version",None)
            if self.config.validation.run_checkov and self.validator.checkov_validator is None and not is_checkov_available():
                errors.append("Checkov is unavailable.")
        if not errors and self.config.llm.provider == "copilot" and any(
            model not in self.clients for model in plan["models"]
        ):
            try:
                manifest["provider_models"] = self.config.llm.discover_models(
                    allow_login=allow_browser_auth
                )
                unavailable = set(plan["models"]) - set(manifest["provider_models"])
                if unavailable:
                    errors.append(
                        f"Copilot models unavailable or disabled: {', '.join(sorted(unavailable))}. "
                        "Discover available models and explicitly update study.models."
                    )
            except (ValueError, RuntimeError) as error:
                errors.append(str(error))
        if "azure-bicep" in targets and not self.config.validation.validate_bicep_syntax:
            errors.append(
                "Controlled studies require Bicep compilation for independent structural evaluation."
            )
        errors.extend(plan["cloud_binding_errors"])
        if (
            not errors
            and self.config.cloud.enabled
            and isinstance(self.cloud, AzureStudyBackend)
        ):
            errors.extend(self.cloud.preflight(scenario_ids))
        if errors:
            manifest.update(status="blocked_preflight", preflight_errors=errors)
            save_checkpoint(directory, manifest, self.call_ledger)
            return manifest
        for scenario_id, scenario in plan["scenarios"].items():
            destination = directory / "specifications" / scenario_id
            if resume and destination.exists():
                continue
            for source_id, text in scenario["sources"].items():
                path = destination / "sources" / f"{source_id}.yml"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            _write_json(destination / "resolved.json", scenario["specification"])
            _write_json(destination / "contract.json", scenario["contract"])
        for index, job in enumerate(plan["schedule"], 1):
            if index <= len(manifest["trials"]):
                continue
            trial_directory = directory / f"trial-{index:05d}"
            try:
                if job["model"] not in self.clients:
                    self.clients[job["model"]] = replace(
                        self.config.llm, model_name=job["model"]
                    ).create_client()
            except ValueError as error:
                manifest.update(
                    status="blocked_model_configuration", error=self._redact(str(error))
                )
                save_checkpoint(directory, manifest, self.call_ledger)
                return manifest
            record = self._trial(
                job, plan["scenarios"][job["scenario_id"]], trial_directory
            )
            manifest["trials"].append(record)
            manifest["generation_requests"] = len(self.call_ledger)
            manifest["physical_model_calls"] = (
                None if self.config.llm.provider == "copilot" or resume else len(self.call_ledger)
            )
            manifest["paid_execution"] = True
            save_checkpoint(directory, manifest, self.call_ledger)
        manifest["summary"] = summarize_trials(
            manifest["trials"],
            seed=self.config.study.random_seed,
            samples=self.config.study.bootstrap_samples,
        )
        manifest["summary"]["usage"] = {
            "accounting": "Unique execution/model totals count each saved request once. Condition attribution includes the shared initial candidate in each workflow; never sum condition rows as billing totals.",
            "unique_execution": call_usage(self.call_ledger),
            "unique_by_model": {
                model: call_usage([call for call in self.call_ledger if call["model"] == model])
                for model in plan["models"]
            },
            "workflow_by_model_condition": {
                model: {
                    arm: workflow_usage([trial["conditions"][arm] for trial in manifest["trials"] if trial["model"] == model])
                    for arm in ARMS
                } for model in plan["models"]
            },
        }
        manifest["status"] = (
            "completed"
            if all(
                not condition.get("operational_error")
                for trial in manifest["trials"]
                for condition in trial["conditions"].values()
            )
            else "completed_with_operational_failures"
        )
        manifest["retained_resource_groups"] = [
            condition["cloud"]["retained_resource_group"]
            for trial in manifest["trials"]
            for condition in trial["conditions"].values()
            if condition["cloud"].get("retained_resource_group")
        ]
        manifest["elapsed_seconds"] = manifest.get("elapsed_seconds", 0) + time.perf_counter() - started
        manifest["completed_at_utc"] = datetime.now(UTC).isoformat()
        _write_json(directory / "summary.json", manifest["summary"])
        save_checkpoint(directory, manifest, self.call_ledger)
        return manifest

    @staticmethod
    def _target_prompt(target: str) -> str:
        dialect = (
            "Generate a complete resource-group-scoped Azure Bicep template for the supplied requirements."
            if target=="azure-bicep" else
            f"Generate Terraform HCL resource blocks for {TARGETS[target]['cloud']}. The harness supplies the pinned official provider configuration and region. Do not include terraform, provider, backend, module, data, variable, local or output blocks. Use literal values and direct resource references; executable provisioners and dynamic resource expansion are unsupported by the static validator."
        )
        return dialect + "\nChoose the architecture, names, addressing and relationships needed to satisfy the high-level scenario. Do not deploy application workloads or runtime probe VMs. Return complete code only, without fences or prose. Static validation does not prove network behavior.\n"

    def _redact(self, text: str) -> str:
        for value in (
            self.config.llm.azure_api_key,
            self.config.llm.openai_api_key,
            self.config.llm.anthropic_api_key,
        ):
            if value:
                text = text.replace(value, "[REDACTED]")
        return text

    def _generate(self, model: str, prompt: str, directory: Path, target: str = "azure-bicep") -> dict[str, Any]:
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
        started = time.perf_counter()
        record: dict[str, Any] = {
            "model": model,
            "target":target,
            "prompt_sha256": _sha256(prompt),
            "directory": str(directory),
            "usage": None,
            "cost_usd": None,
            "status": "generation_failed",
        }
        client = self.clients[model]
        try:
            response = client(prompt)
            if not isinstance(response, str) or not response.strip():
                raise ValueError("Model returned empty/non-text output.")
            template = _clean_bicep_response(response)
            (directory / "response.txt").write_text(response, encoding="utf-8")
            (directory / TARGETS[target]["file"]).write_text(template, encoding="utf-8")
            record.update(
                status="generated",
                template_sha256=_sha256(template),
                response_sha256=_sha256(response),
            )
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
            record["error"] = self._redact(str(error))
        usage = getattr(client, "last_usage", None)
        record["response_metadata"] = getattr(client, "last_response_metadata", {})
        if isinstance(usage, dict) and all(
            type(usage.get(key)) is int and usage[key] >= 0
            for key in ("input_tokens", "output_tokens")
        ):
            record["usage"] = {
                key: usage[key] for key in ("input_tokens", "output_tokens")
            }
            study = self.config.study
            input_price, output_price = study.model_prices.get(
                model,
                [study.input_usd_per_million, study.output_usd_per_million],
            )
            if (
                self.config.llm.provider != "copilot"
                and input_price is not None
                and output_price is not None
            ):
                record["cost_usd"] = (
                    usage["input_tokens"] * input_price
                    + usage["output_tokens"] * output_price
                ) / 1_000_000
        record["generation_seconds"] = time.perf_counter() - started
        self.call_ledger.append(record)
        _write_json(directory / "generation.json", record)
        return record

    def _visible(self, candidate: dict[str, Any], scenario_id: str) -> dict[str, Any]:
        if candidate["status"] != "generated":
            return {"generation": {"status": "failed", "error": candidate["error"]}}
        path = Path(candidate["directory"])
        started = time.perf_counter()
        try:
            target = candidate.get("target","azure-bicep")
            if target == "azure-bicep":
                validation = self.validator.validate_candidate(path / "template.bicep",scenario_id)
            else:
                compiled = self.terraform.validate(path / "main.tf",target)
                validation = {"terraform":compiled,"conftest":{"status":"disabled","reason":"ARM-only Rego policies are not applicable to Terraform."}}
                validation["checkov"] = (
                    self.validator.validate_checkov(path / "main.tf",scenario_id,"terraform")
                    if self.config.validation.run_checkov and compiled["status"]=="passed" else
                    {"status":"not_run","reason":"Terraform validation did not pass."}
                    if self.config.validation.run_checkov else {"status":"disabled"}
                )
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            validation = {
                "validator": {"status": "error", "error": self._redact(str(error))}
            }
        candidate["validation_seconds"] = time.perf_counter() - started
        _write_json(path / "validation.json", validation)
        return validation

    @staticmethod
    def _passed(validation: dict[str, Any]) -> bool:
        return bool(validation) and all(
            value.get("status") in ("passed", "disabled")
            for value in validation.values()
        )

    def _trial(
        self, job: dict[str, Any], scenario: dict[str, Any], directory: Path
    ) -> dict[str, Any]:
        spec = render_requirements(scenario["specification"])
        target = scenario.get("target","azure-bicep")
        source_file = TARGETS[target]["file"]
        generation_options = {"target":target} if target != "azure-bicep" else {}
        prompt = (
            (self._target_prompt(target) if "target" in scenario else COMMON_PROMPT)
            + "\nScenario:\n"
            + spec
        )
        initial = self._generate(job["model"], prompt, directory / "shared-initial",**generation_options)
        initial_validation = self._visible(initial, job["scenario_id"])
        trajectories = {}
        for arm in job["arm_order"]:
            candidates = [initial]
            validations = [initial_validation]
            limit = 1 if arm == "one_shot" else self.config.study.max_iterations
            for iteration in range(2, limit + 1):
                if candidates[-1]["status"] != "generated" or self._passed(
                    validations[-1]
                ):
                    break
                previous = (
                    Path(candidates[-1]["directory"]) / source_file
                ).read_text(encoding="utf-8")
                instruction = "Review and improve the complete template against the scenario. No validator diagnostics are supplied."
                if arm == "tool_feedback":
                    instruction = (
                        "Repair the template using these visible validator diagnostics:\n"
                        + json.dumps(validations[-1], indent=2)
                    )
                revised = self._generate(
                    job["model"],
                    prompt + "\n" + instruction + "\nCurrent template:\n" + previous,
                    directory / arm / f"iteration-{iteration:02d}",
                    **generation_options,
                )
                candidates.append(revised)
                validations.append(self._visible(revised, job["scenario_id"]))
            trajectories[arm] = (candidates, validations)
        # Evaluation begins only after all model trajectories have been frozen.
        conditions = {}
        for arm in ARMS:
            candidates, validations = trajectories[arm]
            started = time.perf_counter()
            evaluations = []
            for candidate in candidates:
                parameters = {
                    **self.scenario_parameters.get(job["scenario_id"], self.parameters),
                    "studySuffix": "local",
                }
                evaluation = {
                    "status": "not_assessed", "checks": [],
                    "reason": "Human-written requirements await independent human review; no resource-shape oracle is applied.",
                } if self.config.study.assessment_mode == "human_review" else {
                    "status": "not_automated", "checks": [],
                    "reason": "No independent high-level requirements evaluator is implemented.",
                } if "target" in scenario else evaluate_structure(
                    Path(candidate["directory"]) / "template.json",
                    job["scenario_id"],
                    parameters,
                )
                evaluations.append(evaluation)
                _write_json(
                    Path(candidate["directory"]) / "structural-acceptance.json",
                    evaluation,
                )
            final = candidates[-1]
            visible_passed = self._passed(validations[-1])
            structural_passed = None if self.config.study.assessment_mode == "human_review" else (
                final["status"] == "generated" and evaluations[-1]["status"] == "passed"
            )
            cloud = {
                "deployment_status": "disabled",
                "runtime_status": "not_run",
                "runtime_checks": [],
            }
            operational_error = final["status"] != "generated" or any(
                value.get("status")
                in (
                    "error",
                    "unavailable_or_failed",
                    "unavailable",
                    "no_checks_executed",
                )
                for value in validations[-1].values()
            )
            if self.config.cloud.enabled:
                if visible_passed and structural_passed:
                    try:
                        cloud = self.cloud.evaluate(
                            Path(final["directory"]) / "template.json",
                            directory / arm / "cloud",
                            job["scenario_id"],
                            scenario["contract"]["runtime_checks"],
                        )
                    except (
                        OSError,
                        ValueError,
                        RuntimeError,
                        subprocess.SubprocessError,
                    ) as error:
                        cloud = {
                            "deployment_status": "blocked",
                            "runtime_checks": [],
                            "reason": self._redact(str(error)),
                        }
                    expected_ids = {
                        item["id"] for item in scenario["contract"]["runtime_checks"]
                    }
                    observed = cloud.get("runtime_checks", [])
                    coverage_complete = (
                        isinstance(observed, list)
                        and len(observed) == len(expected_ids)
                        and all(isinstance(item, dict) for item in observed)
                        and {item.get("id") for item in observed} == expected_ids
                    )
                    runtime_passed = coverage_complete and all(
                        item.get("status") == "passed" for item in observed
                    )
                    cloud["runtime_status"] = (
                        "passed" if runtime_passed else "failed_or_blocked"
                    )
                    operational_error = (
                        operational_error
                        or not coverage_complete
                        or cloud.get("deployment_status") in ("blocked", "error")
                        or cloud.get("cleanup_status") == "failed"
                        or any(
                            item.get("status") == "blocked"
                            for item in (observed if isinstance(observed, list) else [])
                            if isinstance(item, dict)
                        )
                    )
                else:
                    cloud = {
                        "deployment_status": "not_run",
                        "runtime_status": "not_run",
                        "reason": "Candidate did not pass visible and structural checks.",
                    }
            acceptance = None if self.config.study.assessment_mode == "human_review" else (
                visible_passed
                and structural_passed
                and (
                    not self.config.cloud.enabled
                    or (
                        cloud.get("deployment_status") == "passed"
                        and cloud.get("runtime_status") == "passed"
                    )
                )
            )
            costs = [item["cost_usd"] for item in candidates]
            violation_ids = []
            for validation in validations:
                checkov = validation.get("checkov", {})
                violation_ids.append(
                    {
                        (str(item["check_id"]), str(item.get("resource", "unknown")))
                        for item in checkov.get("security_violations", [])
                        if isinstance(item, dict) and item.get("check_id")
                    }
                    if checkov.get("status") in ("passed", "failed")
                    else None
                )
            conditions[arm] = {
                "accepted": acceptance,
                "structural_accepted": structural_passed,
                "requirement_assessment": {"status": "awaiting_human_review", "decision": None}
                if self.config.study.assessment_mode == "human_review" else None,
                "acceptance_scope": "human_review_pending"
                if self.config.study.assessment_mode == "human_review"
                else "full_deployment_and_runtime"
                if self.config.cloud.enabled
                else "finite_structural_only",
                "visible_checks_passed": visible_passed,
                "generation_failed": any(
                    item["status"] != "generated" for item in candidates
                ),
                "operational_error": operational_error,
                "attempts": len(candidates),
                "elapsed_seconds": sum(
                    item["generation_seconds"] + item.get("validation_seconds", 0)
                    for item in candidates
                )
                + time.perf_counter()
                - started,
                "cost_usd": sum(costs)
                if all(cost is not None for cost in costs)
                else None,
                "usage": {
                    key: sum(item["usage"][key] for item in candidates)
                    for key in ("input_tokens", "output_tokens")
                }
                if all(item["usage"] is not None for item in candidates)
                else None,
                "usage_accounting": call_usage(candidates),
                "candidates": [item["directory"] for item in candidates],
                "structural_evaluations": evaluations,
                "cloud": cloud,
                "new_security_check_failures": [
                    [
                        {"check_id": check_id, "resource": resource}
                        for check_id, resource in sorted(current - previous)
                    ]
                    if current is not None and previous is not None
                    else None
                    for previous, current in pairwise(violation_ids)
                ],
            }
        record = {
            **job,
            "family": scenario["family"],
            "specification_sha256": scenario["specification_sha256"],
            "conditions": conditions,
        }
        if self.config.study.assessment_mode == "human_review":
            _write_json(directory / "requirements-review.json", {
                "status": "awaiting_human_review",
                "requirements": spec,
                "scope": "Review preparation only. Model and condition are not blinded. No human evaluation or quality score has been recorded.",
                "candidates": {
                    arm: {"artifact_directory": value["candidates"][-1], "decision": None, "rationale": None}
                    for arm, value in conditions.items()
                },
            })
        _write_json(directory / "result.json", record)
        return record
