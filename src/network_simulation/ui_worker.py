"""Validated static-study operations shared by the local UI and CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from network_simulation.configuration import LLMConfig, POCConfig
from network_simulation.configuration.study import StudyConfig
from network_simulation.configuration.validation import ValidationConfig
from network_simulation.study import ControlledStudyRunner
from network_simulation.study_state import execution_lock, read_checkpoint


def inside(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("A nonempty workspace-relative path is required.")
    if Path(value).is_absolute():
        raise ValueError("Use a relative path within the permitted workspace directory.")
    target = (root / value).resolve(strict=True)
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Path resolves outside its permitted workspace directory.")
    return target


def load_run_config(directory: Path) -> tuple[POCConfig, list[str]]:
    manifest = read_checkpoint(directory)["manifest"] if (directory / "checkpoint.json").is_file() else json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("mode") != "controlled_study" or manifest.get("schema_version") != 1:
        raise ValueError("Unsupported source execution.")
    if manifest.get("cloud", {}).get("enabled") is not False:
        raise ValueError("UI and resume operations support static-only studies.")
    snapshot = directory / "config.yaml"
    if snapshot.is_file():
        config = POCConfig.load_yaml(str(snapshot))
    else:
        if manifest.get("provider") != "copilot":
            raise ValueError("Legacy rerun requires a Copilot run or a saved config.yaml.")
        config = POCConfig()
        config.llm.provider = "copilot"
        config.llm.max_tokens = manifest["generation_settings"]["max_output_tokens"]
        config.study = StudyConfig(**manifest["study"])
        config.validation = ValidationConfig(**manifest["validation"])
        config.experiment.output_directory = str(directory.parent)
    if config.cloud.enabled or not isinstance(manifest.get("scenarios"), dict) or not manifest["scenarios"]:
        raise ValueError("Invalid static source configuration or scenarios.")
    config.study.validate()
    return config, manifest.get("requested_scenarios",list(manifest["scenarios"]))


def settings(config: POCConfig, scenarios: list[str]) -> dict[str, Any]:
    return {
        "models": config.study.models or [config.llm.model_name],
        "targets":config.study.targets,
        "scenarios": scenarios, "repetitions": config.study.repetitions,
        "max_iterations": config.study.max_iterations,
        "random_seed": config.study.random_seed, "max_tokens": config.llm.max_tokens,
    }


def options(workspace: Path) -> dict[str, Any]:
    configs = []
    warnings = []
    for filename in sorted((workspace / "configs").glob("*")):
        if filename.suffix not in (".yaml", ".yml"):
            continue
        try:
            config = POCConfig.load_yaml(str(filename))
            if config.cloud.enabled:
                continue
            scenarios = config.experiment.pilot_scenarios if config.experiment.experiment_phase == "pilot" else config.experiment.main_scenarios
            configs.append({"config": filename.relative_to(workspace).as_posix(), **settings(config, scenarios)})
        except (ValueError, OSError, yaml.YAMLError) as error:
            warnings.append(f"{filename.name}: {error}")
    return {"configs": configs, "warnings": warnings}


def prepare(workspace: Path, request: dict[str, Any]) -> tuple[ControlledStudyRunner, list[str], Path | None]:
    allowed = {"operation", "config", "source_run", "models", "scenarios",
               "repetitions", "max_iterations", "random_seed", "max_tokens", "login", "targets"}
    if not isinstance(request, dict) or set(request) - allowed:
        raise ValueError("Unknown execution parameters.")
    operation = request.get("operation")
    if operation not in ("new", "resume", "full-rerun"):
        raise ValueError("Choose new, resume, or full-rerun.")
    if type(request.get("login", False)) is not bool:
        raise ValueError("login must be a boolean.")
    source = None
    if operation == "new":
        if "source_run" in request:
            raise ValueError("A new execution cannot specify source_run.")
        configuration = request.get("config")
        if not isinstance(configuration, str):
            raise ValueError("Select a configuration.")
        filename = inside(workspace / "configs", configuration.replace("\\", "/").removeprefix("configs/"))
        config = POCConfig.load_yaml(str(filename))
        scenarios = config.experiment.pilot_scenarios if config.experiment.experiment_phase == "pilot" else config.experiment.main_scenarios
    else:
        if "config" in request:
            raise ValueError("Resume/rerun uses the source execution configuration.")
        source = inside(workspace / "results", request.get("source_run"))
        config, scenarios = load_run_config(source)
    if config.cloud.enabled:
        raise ValueError("The UI never permits Azure deployment.")
    if request.get("login") and config.llm.provider != "copilot":
        raise ValueError("Browser sign-in is supported only by the Copilot provider.")
    if operation == "resume":
        if set(request) - {"operation", "source_run", "login"}:
            raise ValueError("Resume cannot change frozen parameters; use full-rerun.")
        read_checkpoint(source)
        with execution_lock(source):
            pass
    else:
        for name in ("repetitions", "max_iterations", "random_seed"):
            if name in request:
                if type(request[name]) is not int:
                    raise ValueError(f"{name} must be an integer.")
                setattr(config.study, name, request[name])
        if "models" in request:
            if not isinstance(request["models"], list):
                raise ValueError("models must be an array.")
            config.study.models = request["models"]
        if "targets" in request:
            config.study.targets = request["targets"]
        if "scenarios" in request:
            if not isinstance(request["scenarios"], list):
                raise ValueError("scenarios must be an array.")
            scenarios = request["scenarios"]
        if "max_tokens" in request:
            config.llm.max_tokens = request["max_tokens"]
        if type(config.llm.max_tokens) is not int or config.llm.max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer.")
        config.experiment.output_directory = "results/ui-runs"
    if config.llm.provider == "azure_responses":
        credentials = LLMConfig.from_env()
        for name in ("azure_endpoint", "azure_api_key", "azure_tenant_id", "azure_subscription_id"):
            setattr(config.llm, name, getattr(config.llm, name) or getattr(credentials, name))
    return ControlledStudyRunner(workspace_dir=workspace, config=config), scenarios, source


def preview(workspace: Path, request: dict[str, Any]) -> dict[str, Any]:
    runner, scenarios, source = prepare(workspace, request)
    plan = runner.plan(scenarios)
    completed = 0
    if request["operation"] == "resume":
        manifest = read_checkpoint(source)["manifest"]
        for field, value in plan.items():
            if field not in {"paid_execution", "maximum_generation_requests", "maximum_physical_model_calls"} and manifest.get(field) != value:
                raise ValueError(f"Frozen field changed: {field}. Use a full rerun.")
        completed = len(manifest["trials"])
    remaining = len(plan["schedule"]) - completed
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return {
        "digest": digest, "completed": completed, "total": len(plan["schedule"]),
        "targets":runner.config.study.targets,"skipped_variants":plan["skipped_variants"],
        "execution_blockers":plan["execution_blockers"],
        "assessment_mode":runner.config.study.assessment_mode,
        "primary_outcome":plan["primary_outcome"],
        "workflows": remaining * 3,
        "maximum_new_generation_requests": remaining * (1 + 2 * (runner.config.study.max_iterations - 1)),
        "note": "No deployment. "
        + ("Human-written requirements remain unassessed pending independent review; compilation/policy passes are not quality verdicts. " if runner.config.study.assessment_mode == "human_review" else "")
        + "Resume can add requests for archived incomplete trials; backend inference retries remain unknown.",
    }


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("command", choices=("options", "settings", "plan", "run", "explain"))
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    try:
        request = json.load(sys.stdin)
        if args.command == "explain":
            from network_simulation.study_explanation import explain_checks
            if not isinstance(request, dict) or set(request) != {"evaluation", "contract", "template", "evaluator_sha256"}:
                raise ValueError("Invalid explanation evidence.")
            emit(explain_checks(request))
        elif args.command == "options":
            emit(options(workspace))
        elif args.command == "settings":
            if not isinstance(request, dict) or set(request) != {"source_run"}:
                raise ValueError("Expected source_run only.")
            config, scenarios = load_run_config(inside(workspace / "results", request["source_run"]))
            emit(settings(config, scenarios))
        elif args.command == "plan":
            emit(preview(workspace, request))
        else:
            if not isinstance(request, dict) or set(request) != {"parameters", "expected_digest"}:
                raise ValueError("Execution requires a previewed parameter set.")
            parameters = request["parameters"]
            checked = preview(workspace, parameters)
            if checked["digest"] != request["expected_digest"]:
                raise ValueError("Configuration or study sources changed since preview. Preview again.")
            runner, scenarios, source = prepare(workspace, parameters)
            result = runner.run(
                scenarios, allow_browser_auth=parameters.get("login", False),
                resume_from=source if parameters["operation"] == "resume" else None,
                rerun_of=str(source) if parameters["operation"] == "full-rerun" else None,
                on_started=lambda directory: emit({"event": "started", "run": directory.relative_to(workspace / "results").as_posix()}),
            )
            emit({"event": "finished", "status": result["status"],
                  "message": "; ".join(result.get("preflight_errors", [])) or result.get("error") or result["status"],
                  "run": Path(result["output_directory"]).relative_to(workspace / "results").as_posix()})
            return 0 if result["status"] == "completed" else 2
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as error:
        emit({"error": str(error)})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
