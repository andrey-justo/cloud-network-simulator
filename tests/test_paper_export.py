import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("paper_export", ROOT / "docs" / "paper" / "export_results.py")
paper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paper)


def fixture_run(tmp_path):
    run = tmp_path / "study-paper"
    run.mkdir()
    manifest = {
        "schema_version": 1, "mode": "controlled_study", "status": "completed",
        "output_directory": str(run), "models": ["model-one", "model-two"],
        "cloud": {"enabled": False}, "study": {"assessment_mode": "human_review", "max_iterations": 5},
        "generation_settings": {"max_output_tokens": 12000},
        "tool_versions": {}, "validation": {}, "prompt_protocol": "requirements",
        "runner_implementation_sha256": "test", "target_implementation_sha256": {},
        "requested_scenarios": ["NET-11"], "trials": [], "schedule": [],
    }
    calls = []
    for target in paper.TARGETS:
        for model in manifest["models"]:
            candidate = run / f"{target}-{model}"
            candidate.mkdir()
            checks = [{"check_id": "CKV2_AWS_11", "check_name": "Flow logs", "result": "failed"}] * 2
            report = {"bicep" if target == "azure-bicep" else "terraform": {"status": "passed"},
                      "checkov": {"status": "failed", "skipped": 0, "results": checks}}
            (candidate / "validation.json").write_text(json.dumps(report))
            job = {"scenario_id": f"NET-11--{target}", "model": model, "repetition": 1, "target": target}
            manifest["schedule"].append(job)
            manifest["trials"].append({**job, "conditions": {
                arm: {
                    "accepted": None, "structural_accepted": None,
                    "requirement_assessment": {"status": "awaiting_human_review"},
                    "visible_checks_passed": arm == "tool_feedback", "generation_failed": False,
                    "operational_error": False, "elapsed_seconds": 10, "cost_usd": None, "cloud": {},
                    "candidates": [str(candidate)], "attempts": 1, "usage": {"input_tokens": 10, "output_tokens": 5},
                } for arm in paper.ARMS
            }})
            calls.append({"model": model, "directory": str(candidate), "status": "generated",
                          "usage": {"input_tokens": 10, "output_tokens": 5}, "generation_seconds": 1, "cost_usd": None})
    checkpoint = {"schema_version": 1, "manifest": manifest, "calls": calls}
    (run / "checkpoint.json").write_text(json.dumps(checkpoint))
    return run, checkpoint


def test_export_uses_paired_denominators_and_deduplicates_policy_failures(tmp_path):
    run, _ = fixture_run(tmp_path)
    snapshot = paper.export_snapshot(run)
    primary = snapshot["primary"]
    assert primary["paired_trials"] == 6 and primary["workflows"] == 18
    assert primary["unique_usage"]["input_tokens"] == 60
    aws = next(row for row in primary["pooled"] if row["target"] == "aws-terraform" and row["arm"] == "one_shot")
    assert aws["failing_workflows_by_check"]["CKV2_AWS_11"] == 2
    assert primary["matched_intents"] == ["NET-11"]
    assert all(row["n01"] == 1 for row in primary["paired_visible"])
    tex = paper.render_tex(snapshot)
    assert "2/2 (100.0\\%)" in tex
    assert "\\newcommand{\\PrimaryUnits}{6}" in tex
    assert paper.main(["--run", str(run), "--output", str(tmp_path / "generated")]) == 0
    assert (tmp_path / "generated" / "results.json").is_file()


def test_original_completed_snapshot_is_primary_and_retry_is_sensitivity(tmp_path):
    run, original = fixture_run(tmp_path)
    audit = run / "before-checkpoint.json"
    audit.write_text(json.dumps(original))
    current = deepcopy(original)
    current["manifest"]["operational_retries"] = [{"original_checkpoint_file": str(audit), "trial_index": 1, "status": "completed"}]
    current["calls"].append({**current["calls"][0], "directory": str(run / "retry")})
    (run / "checkpoint.json").write_text(json.dumps(current))
    snapshot = paper.export_snapshot(run)
    assert snapshot["primary"]["generation_requests"] == 6
    assert snapshot["sensitivity"]["generation_requests"] == 7
    assert snapshot["primary_source"] == "before-checkpoint.json"
    assert snapshot["primary_checkpoint_sha256"] != snapshot["current_checkpoint_sha256"]
    current["manifest"]["trials"][1]["conditions"]["one_shot"]["elapsed_seconds"] = 99
    (run / "checkpoint.json").write_text(json.dumps(current))
    with pytest.raises(ValueError, match="unaudited paired trial"):
        paper.export_snapshot(run)


def test_missing_usage_is_unknown_instead_of_zero(tmp_path):
    run, checkpoint = fixture_run(tmp_path)
    for call in checkpoint["calls"]:
        call["usage"] = None
    for trial in checkpoint["manifest"]["trials"]:
        for condition in trial["conditions"].values():
            condition["usage"] = None
    (run / "checkpoint.json").write_text(json.dumps(checkpoint))
    snapshot = paper.export_snapshot(run)
    assert snapshot["primary"]["unique_usage"]["input_tokens"] is None
    assert r"\newcommand{\PrimaryInputTokens}{unknown}" in paper.render_tex(snapshot)


def test_missing_generated_validator_artifacts_and_assessed_requirements_fail_explicitly(tmp_path):
    run, checkpoint = fixture_run(tmp_path)
    candidate = Path(checkpoint["calls"][0]["directory"]) / "validation.json"
    candidate.unlink()
    with pytest.raises(ValueError, match="Missing final validator"):
        paper.export_snapshot(run)
    checkpoint["manifest"]["trials"][0]["conditions"]["one_shot"]["accepted"] = True
    with pytest.raises(ValueError, match="unassessed"):
        paper.collect(run, checkpoint)


def test_tex_escaping_and_evidence_relocation_are_safe(tmp_path):
    manifest = {"output_directory": r"C:\original\study"}
    assert paper.evidence_path(tmp_path, manifest, r"C:\original\study\trial\candidate") == tmp_path / "trial" / "candidate"
    with pytest.raises(ValueError):
        paper.evidence_path(tmp_path, manifest, r"C:\another\private")
    assert paper.tex_escape(r"a_b&50%{x}\y") == r"a\_b\&50\%\{x\}\textbackslash{}y"
