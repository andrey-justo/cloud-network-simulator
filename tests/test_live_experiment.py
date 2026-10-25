from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from network_simulation.configuration import POCConfig
from network_simulation.live_experiment import LiveExperimentRunner


def test_live_runner_traces_blocked_preflight_in_configured_directory(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("network_simulation.live_experiment.shutil.which", lambda _: None)
    workspace = Path(__file__).resolve().parents[1]
    config = POCConfig()
    model_calls: list[str] = []
    output_directory = tmp_path / "custom-traces"

    result = LiveExperimentRunner(
        workspace_dir=workspace,
        config=config,
        output_directory=output_directory,
        llm_client=lambda prompt: model_calls.append(prompt) or "unexpected",
    ).run(["NET-01"])

    run_directory = Path(result["output_directory"])
    assert result["status"] == "blocked_missing_validation_tools"
    assert run_directory.parent == output_directory
    assert (run_directory / "manifest.json").is_file()
    assert (run_directory / "scenarios" / "NET-01" / "specification.yml").is_file()
    assert (run_directory / "prompts" / "b1.md").is_file()
    assert model_calls == []


def test_live_runner_records_b1_t1_generation_and_validation_artifacts(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    scenario_directory = workspace / "scenarios" / "specs"
    scenario_directory.mkdir(parents=True)
    (scenario_directory / "NET-01.yml").write_text(
        (project_root / "scenarios" / "specs" / "NET-01.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config = POCConfig()
    config.validation.run_opa_policies = False
    compiler = SimpleNamespace(
        executable="fake-bicep",
        validate=lambda source, output: {
            "status": "passed",
            "source": str(source),
            "compiled_template": str(output),
        },
    )
    checkov = SimpleNamespace(
        validate_template=lambda template_path, scenario_id: {
            "template_path": template_path,
            "scenario_id": scenario_id,
            "passed": 3,
            "failed": 0,
            "skipped": 0,
            "total_checks": 3,
            "security_violations": [],
            "policy_violations": [],
        }
    )
    generated_template = """targetScope = 'resourceGroup'
resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: 'vnet-test'
  location: resourceGroup().location
  properties: {
    addressSpace: { addressPrefixes: ['10.0.0.0/16'] }
    subnets: []
  }
}
"""

    result = LiveExperimentRunner(
        workspace_dir=workspace,
        config=config,
        output_directory=tmp_path / "live-runs",
        llm_client=lambda _prompt: generated_template,
        bicep_compiler=compiler,
        checkov_validator=checkov,
    ).run(["NET-01"])

    scenario_result = result["results"]["NET-01"]
    assert result["status"] == "completed_with_unverified_scenario_acceptance"
    assert scenario_result["scenario_acceptance"] == "not_automated"
    for condition in ("B1", "T1"):
        iteration_directory = (
            Path(result["output_directory"])
            / "scenarios"
            / "NET-01"
            / condition
            / "iteration-01"
        )
        assert (iteration_directory / "prompt.md").is_file()
        assert (
            iteration_directory / "response.txt"
        ).read_text(encoding="utf-8") == generated_template
        assert (iteration_directory / "template.bicep").is_file()
        assert (
            iteration_directory / "template.bicep"
        ).read_text(encoding="utf-8") == generated_template
        assert (iteration_directory / "generation.json").is_file()
        assert (iteration_directory / "validation.json").is_file()
    assert not (workspace / "templates" / "bicep").exists()


def make_runner(tmp_path, *, report=None, responses=None, workspace=None):
    config = POCConfig()
    config.validation.run_opa_policies = False
    config.experiment.run_b1 = False
    config.experiment.t1_max_iterations = 2
    prompts = []
    reports = iter(responses) if responses is not None else None
    checkov = SimpleNamespace(validate_template=lambda *args, **kwargs: (
        next(reports) if reports is not None else report
    ))
    runner = LiveExperimentRunner(
        workspace_dir=workspace or Path(__file__).resolve().parents[1],
        config=config, output_directory=tmp_path / "runs",
        llm_client=lambda prompt: prompts.append(prompt) or "// original candidate\n",
        bicep_compiler=SimpleNamespace(
            executable="fake-bicep", validate=lambda *args: {"status": "passed"},
        ),
        checkov_validator=checkov,
    )
    return runner, prompts


def check_report(*, passed=1, failed=0, skipped=0, parsing_errors=0):
    return {
        "passed": passed, "failed": failed, "skipped": skipped,
        "total_checks": passed + failed + skipped, "parsing_errors": parsing_errors,
    }


@pytest.mark.parametrize(("report", "status"), [
    (check_report(passed=0), "no_checks_executed"),
    (check_report(passed=0, skipped=3), "no_checks_executed"),
    (check_report(parsing_errors=1), "failed"),
    ({}, "unavailable_or_failed"),
])
def test_live_runner_does_not_accept_empty_or_invalid_checkov_results(tmp_path, report, status):
    runner, _ = make_runner(tmp_path, report=report)
    result = runner.run(["NET-01"])
    condition = result["results"]["NET-01"]["conditions"]["T1"]
    assert condition["automated_checks_passed"] is False
    assert condition["iterations"][0]["validation"]["checkov"]["status"] == status


def test_live_runner_preserves_inherited_sources_and_retry_context(tmp_path):
    runner, prompts = make_runner(
        tmp_path, responses=[check_report(passed=0, failed=1), check_report()],
    )
    result = runner.run(["NET-10"])
    scenario = result["results"]["NET-10"]
    assert scenario["context_chain"] == ["NET-08", "NET-10"]
    assert set(scenario["source_sha256"]) == {"NET-08", "NET-10"}
    assert len(prompts) == 2
    for prompt in prompts:
        assert "Application Gateway handles external access through a dedicated gateway subnet" in prompt
        assert "Private Endpoints for data services exist" in prompt
        assert "Sensitive workload with strict security requirements" in prompt
    directory = Path(result["output_directory"]) / "scenarios" / "NET-10"
    assert (directory / "sources" / "NET-08.yml").is_file()
    assert (directory / "sources" / "NET-10.yml").is_file()
    assert scenario["conditions"]["T1"]["iterations_to_automated_pass"] == 2
    assert result["generation_settings"] == {"max_output_tokens": 2000}


@pytest.mark.parametrize("parent", ["MISSING", "NET-10"])
def test_live_runner_blocks_missing_or_cyclic_inheritance(tmp_path, parent):
    workspace = tmp_path / "workspace"
    directory = workspace / "scenarios" / "specs"
    directory.mkdir(parents=True)
    (directory / "NET-10.yml").write_text(f"name: Child\nextends: [{parent}]", encoding="utf-8")
    runner, prompts = make_runner(tmp_path, report=check_report(), workspace=workspace)
    result = runner.run(["NET-10"])
    assert result["results"]["NET-10"]["status"] == "failed_invalid_scenario"
    assert prompts == []


def test_preflight_does_not_probe_disabled_checkov(monkeypatch, tmp_path):
    runner, _ = make_runner(tmp_path)
    runner.checkov_validator = None
    runner.config.validation.run_checkov = False

    def unexpected_probe():
        raise AssertionError("Disabled Checkov must not be probed.")

    monkeypatch.setattr("network_simulation.live_experiment.is_checkov_available", unexpected_probe)
    assert runner._preflight_errors() == []


def test_preflight_records_missing_checkov_before_generation(monkeypatch, tmp_path):
    runner, prompts = make_runner(tmp_path)
    runner.checkov_validator = None
    monkeypatch.setattr("network_simulation.live_experiment.is_checkov_available", lambda: False)
    result = runner.run(["NET-01"])
    assert result["status"] == "blocked_missing_validation_tools"
    assert any("Checkov" in error for error in result["preflight_errors"])
    assert prompts == []
    manifest = json.loads((Path(result["output_directory"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == result["status"]


def test_live_runner_records_checkov_execution_errors(tmp_path):
    runner, _ = make_runner(tmp_path)

    def failed_checkov(*args, **kwargs):
        raise RuntimeError("Checkov execution failed (2): fatal error")

    runner.checkov_validator.validate_template = failed_checkov
    result = runner.run(["NET-01"])
    condition = result["results"]["NET-01"]["conditions"]["T1"]
    assert condition["automated_checks_passed"] is False
    assert "fatal error" in condition["iterations"][0]["validation"]["checkov"]["error"]