from pathlib import Path
import subprocess
import sys
import json

import pytest

from validation.checkov_validator import CheckovValidator
from network_simulation.validation import checkov_validator as adapter


@pytest.fixture
def validator(monkeypatch):
    monkeypatch.setattr(adapter, "is_checkov_available", lambda: True)
    return CheckovValidator(framework="arm")


def test_validator_cli_requires_an_explicit_experiment_artifact(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(project_root / "validation" / "checkov_validator.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "required: template" in result.stderr
    assert not list(tmp_path.iterdir())


def test_checkov_parser_errors_are_not_reported_as_passes(validator) -> None:
    report = validator._parse_checkov_output(
        {
            "results": {"failed_checks": [], "passed_checks": [], "skipped_checks": []},
            "summary": {
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "parsing_errors": 1,
            },
        },
        "template.bicep",
        "NET-01",
    )

    assert report.total_checks == 0
    assert report.parsing_errors == 1


@pytest.mark.parametrize(
    ("returncode", "stdout", "message"),
    [
        (2, "", "execution failed"),
        (0, "", "no JSON report"),
        (0, "invalid json", "Expecting value"),
        (0, "{}", "neither a summary"),
        (0, "[]", "empty report list"),
        (0, '{"summary": {"passed": -1}}', "non-negative integer"),
        (0, '{"summary": [], "failed_checks": []}', "summary must be an object"),
        (1, '{"summary": {"passed": 1}}', "without reporting any failures"),
    ],
)
def test_checkov_rejects_execution_and_report_failures(
    monkeypatch, tmp_path, validator, returncode, stdout, message
) -> None:
    artifact = tmp_path / "template.json"
    artifact.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(adapter.shutil, "which", lambda _: "checkov-test")
    monkeypatch.setattr(
        adapter.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], returncode, stdout, "tool error"),
    )
    with pytest.raises((RuntimeError, ValueError), match=message):
        validator.validate_template(str(artifact))


def test_checkov_retains_failed_checks_and_aggregates_reports(monkeypatch, tmp_path, validator):
    artifact = tmp_path / "template.json"
    artifact.write_text("{}", encoding="utf-8")
    output = [
        {"results": {"failed_checks": [{"check_id": "CKV_AZURE_1"}]}, "summary": {"failed": 1}},
        {"results": {"passed_checks": []}, "summary": {"passed": 2}},
    ]
    monkeypatch.setattr(adapter.shutil, "which", lambda _: "checkov-test")
    monkeypatch.setattr(
        adapter.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 1, json.dumps(output), ""),
    )
    report = validator.validate_template(str(artifact))
    assert (report.total_checks, report.failed, report.passed) == (3, 1, 2)
    assert len(report.security_violations) == 1


def test_checkov_module_fallback_preserves_exit_status(monkeypatch, tmp_path, validator):
    artifact = tmp_path / "template.json"
    artifact.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(adapter.shutil, "which", lambda _: None)

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 2, "", "module crashed")

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="module crashed"):
        validator.validate_template(str(artifact))
    assert calls[0][0] == sys.executable


def test_checkov_discovery_does_not_import_missing_parent(monkeypatch):
    lookups = []
    monkeypatch.setattr(adapter.shutil, "which", lambda _: None)

    def find_spec(name):
        lookups.append(name)
        assert name == "checkov"
        return None

    monkeypatch.setattr(adapter.importlib.util, "find_spec", find_spec)
    assert adapter.is_checkov_available() is False
    with pytest.raises(RuntimeError, match="Checkov not found"):
        CheckovValidator()
    assert lookups == ["checkov", "checkov"]