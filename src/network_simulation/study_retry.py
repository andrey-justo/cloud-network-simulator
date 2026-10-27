"""Explicit, audited retries of operationally failed paired trials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from network_simulation.study import ARMS, ControlledStudyRunner, summarize_trials
from network_simulation.study_state import atomic_json, execution_lock, read_checkpoint, save_checkpoint
from network_simulation.ui_worker import load_run_config
from network_simulation.usage_accounting import call_usage, workflow_usage


def _validate(runner: ControlledStudyRunner, directory: Path, index: int) -> tuple[dict[str, Any], dict[str, Any]]:
    checkpoint = read_checkpoint(directory)
    manifest = checkpoint["manifest"]
    if runner.config.cloud.enabled or manifest.get("cloud", {}).get("enabled") is not False:
        raise ValueError("Operational retries support static studies only.")
    if Path(manifest["output_directory"]).resolve() != directory.resolve():
        raise ValueError("Retry requires the original execution location.")
    if manifest["status"] not in ("completed", "completed_with_operational_failures"):
        raise ValueError("Finish or resume the scheduled execution before retrying a failed trial.")
    if len(manifest["trials"]) != len(manifest["schedule"]):
        raise ValueError("All scheduled trials must be checkpointed before an operational retry.")
    if type(index) is not int or not 1 <= index <= len(manifest["trials"]):
        raise ValueError("Choose a valid 1-based paired-trial index.")
    if not any(value["operational_error"] for value in manifest["trials"][index - 1]["conditions"].values()):
        raise ValueError("Only operational failures may be retried; quality or policy failures are not eligible.")
    plan = runner.plan(manifest.get("requested_scenarios", list(manifest["scenarios"])))
    for field, value in plan.items():
        if field not in {"paid_execution", "maximum_generation_requests", "maximum_physical_model_calls"} and manifest.get(field) != value:
            raise ValueError(f"Retry rejected: frozen study field changed: {field}.")
    return checkpoint, plan


def retry_trial(
    runner: ControlledStudyRunner, directory: Path, index: int, *,
    execute: bool = False, allow_browser_auth: bool = False,
) -> dict[str, Any]:
    directory = directory.resolve()
    with execution_lock(directory):
        checkpoint, plan = _validate(runner, directory, index)
        manifest = checkpoint["manifest"]
        job = manifest["schedule"][index - 1]
        budget = 1 + 2 * (runner.config.study.max_iterations - 1)
        if not execute:
            return {
                "paid_execution": False, "trial_index": index, "job": job,
                "preserved_other_trials": len(manifest["trials"]) - 1,
                "maximum_new_generation_requests": budget,
                "note": "The original result/artifacts and all observed requests remain in the audit. Only this paired trial is replaced.",
            }
        try:
            target = job.get("target", "azure-bicep")
            errors = runner.validator._preflight_errors() if target == "azure-bicep" else runner.terraform.preflight([target], initialize=True)
            if errors:
                raise ValueError("Retry preflight failed: " + "; ".join(errors))
            if job["model"] not in runner.clients:
                available = runner.config.llm.discover_models(allow_login=allow_browser_auth)
                if job["model"] not in available:
                    raise ValueError("The original model is not available; retry cannot substitute another model.")
                runner.clients[job["model"]] = replace(runner.config.llm, model_name=job["model"]).create_client()
            return _execute(runner, directory, index, checkpoint, plan, budget)
        finally:
            runner.terraform.close()


def _execute(runner, directory, index, checkpoint, plan, budget):
    manifest = checkpoint["manifest"]
    runner.call_ledger = checkpoint["calls"]
    original = deepcopy(manifest["trials"][index - 1])
    job = manifest["schedule"][index - 1]
    attempt = directory / "operational-retries" / f"trial-{index:05d}-{uuid4().hex[:8]}"
    attempt.mkdir(parents=True, exist_ok=False)
    atomic_json(attempt / "before-checkpoint.json", checkpoint)
    atomic_json(attempt / "original-result.json", original)
    event = {
        "trial_index": index, "status": "running", "reason": "Explicit retry of operational failure, not quality-based regeneration.",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "original_result_file": str(attempt / "original-result.json"),
        "original_checkpoint_file": str(attempt / "before-checkpoint.json"),
        "retry_implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "replacement_directory": str(attempt / "replacement"),
        "original_completed_at_utc": manifest.get("completed_at_utc"),
        "generation_requests_before": len(runner.call_ledger),
        "maximum_new_generation_requests": budget,
    }
    manifest.setdefault("operational_retries", []).append(event)
    manifest.update(status="started", runner_pid=os.getpid())
    manifest["maximum_generation_requests"] += budget
    save_checkpoint(directory, manifest, runner.call_ledger)
    started = time.perf_counter()
    failure = None
    try:
        result = runner._trial(job, plan["scenarios"][job["scenario_id"]], attempt / "replacement")
        manifest["trials"][index - 1] = result
        event["status"] = "completed"
        for call in runner.call_ledger[:event["generation_requests_before"]]:
            if call["directory"] in {path for condition in original["conditions"].values() for path in condition["candidates"]}:
                call["superseded_by_operational_retry"] = str(attempt)
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as error:
        event.update(status="interrupted", error=runner._redact(str(error)) or type(error).__name__)
        for call in runner.call_ledger[event["generation_requests_before"]:]:
            call["excluded_from_completed_trials"] = True
        unknown = sum(not prompt.with_name("generation.json").is_file() for prompt in attempt.rglob("prompt.txt"))
        event["unknown_interrupted_requests"] = unknown
        manifest["unknown_interrupted_requests"] = manifest.get("unknown_interrupted_requests", 0) + unknown
        failure = error
    event["finished_at_utc"] = datetime.now(UTC).isoformat()
    event["new_generation_requests"] = len(runner.call_ledger) - event["generation_requests_before"]
    manifest["generation_requests"] = len(runner.call_ledger)
    manifest["physical_model_calls"] = None
    manifest["status"] = "completed_with_operational_failures" if any(
        condition["operational_error"] for trial in manifest["trials"] for condition in trial["conditions"].values()
    ) else "completed"
    manifest["elapsed_seconds"] = manifest.get("elapsed_seconds", 0) + time.perf_counter() - started
    manifest["completed_at_utc"] = event["finished_at_utc"]
    manifest["summary"] = summarize_trials(
        manifest["trials"], seed=runner.config.study.random_seed, samples=runner.config.study.bootstrap_samples,
    )
    manifest["summary"]["usage"] = {
        "accounting": "Unique totals include original failed and retry requests once. Condition attribution uses current results, includes shared initial candidates, and must not be summed as billing totals.",
        "unique_execution": call_usage(runner.call_ledger),
        "unique_by_model": {
            model: call_usage([call for call in runner.call_ledger if call["model"] == model])
            for model in manifest["models"]
        },
        "workflow_by_model_condition": {
            model: {
                arm: workflow_usage([trial["conditions"][arm] for trial in manifest["trials"] if trial["model"] == model])
                for arm in ARMS
            } for model in manifest["models"]
        },
    }
    atomic_json(attempt / "audit.json", event)
    save_checkpoint(directory, manifest, runner.call_ledger)
    atomic_json(directory / "summary.json", manifest["summary"])
    if failure is not None:
        raise failure
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--trial", type=int, required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--login", action="store_true")
    args = parser.parse_args(argv)
    try:
        config, _ = load_run_config(args.run.resolve())
        runner = ControlledStudyRunner(workspace_dir=args.workspace.resolve(), config=config)
        result = retry_trial(runner, args.run, args.trial, execute=args.execute, allow_browser_auth=args.login)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"Operational retry failed: {error}\n")
    print(json.dumps(result if not args.execute else {
        "status": result["status"], "paired_trials": len(result["trials"]),
        "generation_requests": result["generation_requests"], "retry": result["operational_retries"][-1],
    }, indent=2))
    return 0 if not args.execute or result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
