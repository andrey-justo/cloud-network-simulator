from pathlib import Path
from types import SimpleNamespace

import pytest

from network_simulation.validation.bicep_compiler import BicepCompiler
from network_simulation.validation.conftest_validator import ConftestValidator


@pytest.mark.parametrize(
    ("returncode", "expected_status"),
    [(0, "passed"), (1, "failed")],
)
def test_bicep_compiler_reports_process_result(
    monkeypatch, tmp_path, returncode, expected_status
) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=returncode,
            stdout="compiled" if returncode == 0 else "",
            stderr="syntax error" if returncode else "",
        )

    monkeypatch.setattr(
        "network_simulation.validation.bicep_compiler.subprocess.run", fake_run
    )
    source = tmp_path / "input.bicep"
    output = tmp_path / "output.json"
    source.write_text("// test", encoding="utf-8")

    result = BicepCompiler(executable="bicep-test").validate(source, output)

    assert result["status"] == expected_status
    assert calls[0][:2] == ["bicep-test", "build"]
    assert str(source) in calls[0]
    assert str(output) in calls[0]


def test_bicep_compiler_reports_missing_executable(tmp_path) -> None:
    result = BicepCompiler(executable="").validate(
        tmp_path / "input.bicep",
        tmp_path / "output.json",
    )

    assert result["status"] == "unavailable"


def test_bicep_compiler_honors_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("BICEP_CLI", "custom-bicep")
    monkeypatch.setattr("network_simulation.validation.bicep_compiler.shutil.which", lambda _: None)

    assert BicepCompiler().executable == "custom-bicep"


def test_conftest_validator_uses_policy_directory(monkeypatch, tmp_path) -> None:
    policy_directory = tmp_path / "policies"
    policy_directory.mkdir()
    (policy_directory / "network.rego").write_text("package main", encoding="utf-8")
    template = tmp_path / "compiled.json"
    template.write_text("{}", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="{\"successes\": 1}", stderr="")

    monkeypatch.setattr(
        "network_simulation.validation.conftest_validator.subprocess.run", fake_run
    )

    result = ConftestValidator(executable="conftest-test").validate(
        template,
        policy_directory,
    )

    assert result["status"] == "passed"
    assert calls[0][0:2] == ["conftest-test", "test"]
    assert str(policy_directory) in calls[0]


def test_conftest_validator_requires_policies(tmp_path) -> None:
    template = tmp_path / "compiled.json"
    template.write_text("{}", encoding="utf-8")

    result = ConftestValidator(executable="conftest-test").validate(
        template,
        tmp_path / "empty-policies",
    )

    assert result["status"] == "unavailable"