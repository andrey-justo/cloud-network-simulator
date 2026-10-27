"""Export an auditable, aggregate-only paper snapshot from saved study evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from network_simulation.study_state import atomic_json, read_checkpoint
from network_simulation.usage_accounting import call_usage, workflow_usage

ARMS = ("one_shot", "blind_refinement", "tool_feedback")
TARGETS = ("azure-bicep", "azure-terraform", "aws-terraform")
TARGET_LABELS = {"azure-bicep": "Azure/Bicep", "azure-terraform": "Azure/Terraform", "aws-terraform": "AWS/Terraform"}
ARM_LABELS = {"one_shot": "S", "blind_refinement": "B", "tool_feedback": "F"}


def tex_escape(value: Any) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in str(value))


def evidence_path(run: Path, manifest: dict, recorded: str) -> Path:
    flavor = PureWindowsPath if PureWindowsPath(manifest["output_directory"]).is_absolute() else Path
    relative = flavor(recorded).relative_to(flavor(manifest["output_directory"]))
    candidate = run.joinpath(*relative.parts).resolve()
    if not candidate.is_relative_to(run.resolve()):
        raise ValueError("Evidence resolves outside the selected execution.")
    return candidate


def file_hash(filename: Path) -> str:
    return hashlib.sha256(filename.read_bytes()).hexdigest()


def validate_dataset(checkpoint: dict) -> None:
    if checkpoint.get("schema_version") != 1 or not isinstance(checkpoint.get("calls"), list):
        raise ValueError("Unsupported paper evidence checkpoint.")
    manifest = checkpoint["manifest"]
    if manifest.get("study", {}).get("assessment_mode") != "human_review":
        raise ValueError("This paper exporter accepts requirements-only human-review studies.")
    if manifest.get("cloud", {}).get("enabled") is not False:
        raise ValueError("The paper describes static-only observations.")
    if manifest["status"] not in ("completed", "completed_with_operational_failures"):
        raise ValueError("Primary paper evidence must be a completed execution.")
    if len(manifest["trials"]) != len(manifest["schedule"]):
        raise ValueError("Primary paper evidence has incomplete scheduled trials.")
    if len(manifest["models"]) != 2:
        raise ValueError("The draft's model-stratified tables require exactly two model identifiers.")
    if len({call["directory"] for call in checkpoint["calls"]}) != len(checkpoint["calls"]):
        raise ValueError("Duplicate request directories would double-count token usage.")
    for trial, job in zip(manifest["trials"], manifest["schedule"]):
        if any(trial.get(key) != job.get(key) for key in ("scenario_id", "model", "repetition", "target")):
            raise ValueError("Trials do not match the saved schedule.")
        if set(trial["conditions"]) != set(ARMS):
            raise ValueError("Incomplete paired condition evidence.")
        for condition in trial["conditions"].values():
            if condition["accepted"] is not None or condition["structural_accepted"] is not None:
                raise ValueError("Requirement satisfaction must remain explicitly unassessed.")


def collect(run: Path, checkpoint: dict) -> dict:
    validate_dataset(checkpoint)
    manifest = checkpoint["manifest"]
    evidence_hashes = {}
    rows = []
    for trial in manifest["trials"]:
        for arm in ARMS:
            condition = trial["conditions"][arm]
            candidate = evidence_path(run, manifest, condition["candidates"][-1])
            report_file = candidate / "validation.json"
            if report_file.is_file():
                report = json.loads(report_file.read_text(encoding="utf-8"))
                evidence_hashes[report_file.relative_to(run).as_posix()] = file_hash(report_file)
            elif condition["generation_failed"]:
                report = {}
            else:
                raise ValueError(f"Missing final validator evidence: {report_file}")
            target = trial.get("target", "azure-bicep")
            compilation = report.get("bicep" if target == "azure-bicep" else "terraform", {}).get("status", "unknown")
            checkov = report.get("checkov", {})
            failed_checks = {
                item["check_id"]: item["check_name"]
                for item in checkov.get("results", []) if item["result"] == "failed"
            }
            rows.append({
                "scenario": trial["scenario_id"], "intent": trial["scenario_id"].split("--")[0],
                "model": trial["model"], "target": target, "arm": arm, "condition": condition,
                "compilation": compilation, "checkov_status": checkov.get("status", "unknown"),
                "skipped_checks": checkov.get("skipped", 0), "failed_checks": failed_checks,
            })

    def aggregate(selected):
        failures = Counter(check for row in selected for check in row["failed_checks"])
        return {
            "n": len(selected),
            "compiled": sum(row["compilation"] == "passed" for row in selected),
            "compilation_unknown": sum(row["compilation"] not in ("passed", "failed") for row in selected),
            "visible_passed": sum(row["condition"]["visible_checks_passed"] for row in selected),
            "operational_errors": sum(row["condition"]["operational_error"] for row in selected),
            "generation_failures": sum(row["condition"]["generation_failed"] for row in selected),
            "checkov_statuses": dict(Counter(row["checkov_status"] for row in selected)),
            "skipped_check_instances": sum(row["skipped_checks"] for row in selected),
            "failing_workflows_by_check": dict(sorted(failures.items())),
            "mean_attempts": sum(row["condition"]["attempts"] for row in selected) / len(selected) if selected else None,
            "mean_elapsed_seconds": sum(row["condition"]["elapsed_seconds"] for row in selected) / len(selected) if selected else None,
        }

    pooled, stratified, paired = [], [], []
    for target in TARGETS:
        for arm in ARMS:
            pooled.append({"target": target, "arm": arm, **aggregate([row for row in rows if row["target"] == target and row["arm"] == arm])})
        for model in manifest["models"]:
            for arm in ARMS:
                stratified.append({"target": target, "model": model, "arm": arm, **aggregate([
                    row for row in rows if row["target"] == target and row["model"] == model and row["arm"] == arm
                ])})
            selected = [trial for trial in manifest["trials"] if trial.get("target", "azure-bicep") == target and trial["model"] == model]
            for control in ("one_shot", "blind_refinement"):
                transitions = Counter(
                    f"{int(trial['conditions'][control]['visible_checks_passed'])}{int(trial['conditions']['tool_feedback']['visible_checks_passed'])}"
                    for trial in selected
                )
                paired.append({
                    "target": target, "model": model, "control": control, "n": len(selected),
                    **{f"n{key}": transitions[key] for key in ("00", "01", "10", "11")},
                    "difference_percentage_points": 100 * (transitions["01"] - transitions["10"]) / len(selected) if selected else None,
                })
    intents = {
        target: {row["intent"] for row in rows if row["target"] == target}
        for target in TARGETS
    }
    matched = set.intersection(*intents.values())
    matched_pooled = [
        {"target": target, "arm": arm, **aggregate([
            row for row in rows if row["target"] == target and row["arm"] == arm and row["intent"] in matched
        ])} for target in TARGETS for arm in ARMS
    ]
    calls = checkpoint["calls"]
    return {
        "status": manifest["status"], "completed_at_utc": manifest.get("completed_at_utc"),
        "models": manifest["models"], "study": manifest["study"],
        "generation_settings": manifest["generation_settings"],
        "tool_versions": manifest["tool_versions"], "validation": manifest["validation"],
        "prompt_protocol": manifest["prompt_protocol"],
        "runner_implementation_sha256": manifest["runner_implementation_sha256"],
        "target_implementation_sha256": manifest["target_implementation_sha256"],
        "specification_count": len(manifest["requested_scenarios"]),
        "target_variant_counts": {target: len(intents[target]) for target in TARGETS},
        "matched_intents": sorted(matched), "paired_trials": len(manifest["trials"]),
        "workflows": len(rows), "operational_failure_workflows": sum(row["condition"]["operational_error"] for row in rows),
        "generation_requests": len(calls), "unique_usage": call_usage(calls),
        "unique_by_model": {model: call_usage([call for call in calls if call["model"] == model]) for model in manifest["models"]},
        "attributed_by_model_condition": [
            {"model": model, "arm": arm, **workflow_usage([
                trial["conditions"][arm] for trial in manifest["trials"] if trial["model"] == model
            ])} for model in manifest["models"] for arm in ARMS
        ],
        "sdk_versions": sorted({call.get("response_metadata", {}).get("sdk_version", "unreported") for call in calls}),
        "pooled": pooled, "by_model": stratified, "paired_visible": paired,
        "matched_pooled": matched_pooled, "validator_artifact_sha256": evidence_hashes,
    }


def export_snapshot(run: Path) -> dict:
    run = run.resolve()
    current = read_checkpoint(run)
    manifest = current["manifest"]
    sources = ([run / "checkpoint.json"] if (run / "checkpoint.json").is_file() else []) + list(run.glob("checkpoint-recovery-*.json"))
    current_file = max(sources, key=lambda filename: filename.stat().st_mtime_ns)
    history = manifest.get("operational_retries", [])
    primary_file = evidence_path(run, manifest, history[0]["original_checkpoint_file"]) if history else current_file
    primary = json.loads(primary_file.read_text(encoding="utf-8"))
    if history:
        original = primary["manifest"]
        if original["schedule"] != manifest["schedule"] or original["study"] != manifest["study"]:
            raise ValueError("Retry sensitivity must preserve the original schedule and study settings.")
        changed_indices = {event["trial_index"] - 1 for event in history}
        if any(index < 0 or index >= len(original["trials"]) for index in changed_indices):
            raise ValueError("Retry audit contains an invalid trial index.")
        if any(
            old != new for index, (old, new) in enumerate(zip(original["trials"], manifest["trials"]))
            if index not in changed_indices
        ):
            raise ValueError("An unaudited paired trial changed between primary and sensitivity evidence.")
    return {
        "schema_version": 1, "exported_at_utc": datetime.now(UTC).isoformat(),
        "run_id": run.name,
        "primary_source": primary_file.relative_to(run).as_posix(),
        "primary_checkpoint_sha256": file_hash(primary_file),
        "current_checkpoint_sha256": file_hash(current_file),
        "analysis_policy": "Original completed outcomes are primary, including operational failures. Audited operational replacements are a separate sensitivity analysis; they are not independent repetitions.",
        "primary": collect(run, primary),
        "sensitivity": collect(run, current) if manifest["status"] in ("completed", "completed_with_operational_failures") else None,
        "retry_audit": [
            {key: event[key] for key in ("trial_index", "status", "reason", "started_at_utc", "finished_at_utc", "new_generation_requests") if key in event}
            for event in history
        ],
    }


def render_tex(snapshot: dict) -> str:
    primary = snapshot["primary"]
    model_ids = {model: f"M{index}" for index, model in enumerate(primary["models"], 1)}
    lines = ["% Generated by export_results.py. Do not edit numerical results by hand."]

    def macro(name, value):
        lines.append(r"\newcommand{\%s}{%s}" % (name, tex_escape(value)))

    def table(name, rows):
        lines.append(r"\newcommand{\%s}{%%" % name)
        lines.extend(" & ".join(tex_escape(value) for value in row) + r" \\" for row in rows)
        lines.append("}")

    def rate(value, n):
        return f"{value}/{n} ({100 * value / n:.1f}\\%)" if n else "--"

    def tokens(value):
        return f"{value:,}" if value is not None else "unknown"

    def rate_table(name, rows, model=False):
        lines.append(r"\newcommand{\%s}{%%" % name)
        for row in rows:
            values = [tex_escape(TARGET_LABELS[row["target"]])]
            if model:
                values.append(model_ids[row["model"]])
            values.extend([
                ARM_LABELS[row["arm"]], str(row["n"]),
                rate(row["compiled"], row["n"]), rate(row["visible_passed"], row["n"]),
            ])
            lines.append(" & ".join(values) + r" \\")
        lines.append("}")

    macro("StudyRun", snapshot["run_id"])
    macro("PrimarySourceHash", snapshot["primary_checkpoint_sha256"])
    macro("PrimaryUnits", primary["paired_trials"])
    macro("PrimaryWorkflows", primary["workflows"])
    macro("SpecificationCount", primary["specification_count"])
    macro("VariantCount", sum(primary["target_variant_counts"].values()))
    macro("MatchedIntentCount", len(primary["matched_intents"]))
    macro("PrimaryRequests", primary["generation_requests"])
    macro("PrimaryKnownRequests", primary["unique_usage"]["known_requests"])
    macro("PrimaryUnknownRequests", primary["unique_usage"]["unknown_requests"])
    macro("PrimaryInputTokens", tokens(primary["unique_usage"]["input_tokens"]))
    macro("PrimaryOutputTokens", tokens(primary["unique_usage"]["output_tokens"]))
    macro("PrimaryTotalTokens", tokens(primary["unique_usage"]["total_tokens"]))
    macro("PrimaryOperationalWorkflows", primary["operational_failure_workflows"])
    for index, model in enumerate(primary["models"], 1):
        macro("Model" + ("One" if index == 1 else "Two"), model)
    macro("IterationBudget", primary["study"]["max_iterations"])
    macro("OutputTokenBudget", f'{primary["generation_settings"]["max_output_tokens"]:,}')
    for key, name in (("one_shot", "Initial"), ("tool_feedback", "Feedback")):
        row = next(row for row in primary["pooled"] if row["target"] == "aws-terraform" and row["arm"] == key)
        macro("AWS" + name + "Compiled", row["compiled"])
        macro("AWS" + name + "Passed", row["visible_passed"])
        macro("AWS" + name + "Units", row["n"])
    aws_initial = next(row for row in primary["pooled"] if row["target"] == "aws-terraform" and row["arm"] == "one_shot")
    macro("AWSInitialFlowFailures", aws_initial["failing_workflows_by_check"].get("CKV2_AWS_11", 0))
    macro("AWSInitialDefaultSGFailures", aws_initial["failing_workflows_by_check"].get("CKV2_AWS_12", 0))
    rate_table("PooledResultRows", primary["pooled"])
    rate_table("ModelResultRows", primary["by_model"], model=True)
    rate_table("MatchedResultRows", primary["matched_pooled"])
    table("PairedResultRows", [
        [TARGET_LABELS[row["target"]], model_ids[row["model"]], row["n"], row["n00"], row["n01"], row["n10"], row["n11"], f'{row["difference_percentage_points"]:+.1f}']
        for row in primary["paired_visible"] if row["control"] == "blind_refinement"
    ])
    table("AWSPolicyRows", [
        [model_ids[row["model"]], ARM_LABELS[row["arm"]], row["n"], row["compiled"],
         row["failing_workflows_by_check"].get("CKV2_AWS_11", 0),
         row["failing_workflows_by_check"].get("CKV2_AWS_12", 0), row["visible_passed"], f'{row["mean_attempts"]:.2f}']
        for row in primary["by_model"] if row["target"] == "aws-terraform"
    ])
    table("UniqueUsageRows", [
        [model_ids[model], value["known_requests"], value["unknown_requests"],
         tokens(value["input_tokens"]), tokens(value["output_tokens"]), tokens(value["total_tokens"])]
        for model, value in primary["unique_by_model"].items()
    ])
    table("AttributedUsageRows", [
        [model_ids[row["model"]], ARM_LABELS[row["arm"]], row["workflows"], row["known_requests"], row["unknown_requests"],
         tokens(row["input_tokens"]), tokens(row["output_tokens"]), f'{row["mean_elapsed_seconds"]:.1f}']
        for row in primary["attributed_by_model_condition"]
    ])
    sensitivity = snapshot["sensitivity"]
    if sensitivity is not None:
        macro("RecoveredRequests", sensitivity["generation_requests"])
        macro("RetryNewRequests", sensitivity["generation_requests"] - primary["generation_requests"])
        macro("RecoveredOperationalWorkflows", sensitivity["operational_failure_workflows"])
        macro("RecoveredTotalTokens", tokens(sensitivity["unique_usage"]["total_tokens"]))
        rate_table("RecoveredResultRows", sensitivity["pooled"])
    else:
        raise ValueError("Wait for the authorized operational retry to finish before exporting the sensitivity table.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "generated")
    args = parser.parse_args(argv)
    try:
        snapshot = export_snapshot(args.run)
        tex = render_tex(snapshot)
        args.output.mkdir(parents=True, exist_ok=True)
        atomic_json(args.output / "results.json", snapshot)
        (args.output / "results.tex").write_text(tex, encoding="utf-8")
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"Paper export failed: {error}\n")
    print(json.dumps({
        "primary_source": snapshot["primary_source"],
        "paired_trials": snapshot["primary"]["paired_trials"],
        "primary_requests": snapshot["primary"]["generation_requests"],
        "current_requests": snapshot["sensitivity"]["generation_requests"],
        "output": str(args.output.resolve()), "paid_execution": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
