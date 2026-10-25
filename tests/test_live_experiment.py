from pathlib import Path
from types import SimpleNamespace

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
    workspace = Path(__file__).resolve().parents[1]
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
        assert (iteration_directory / "generation.json").is_file()
        assert (iteration_directory / "validation.json").is_file()