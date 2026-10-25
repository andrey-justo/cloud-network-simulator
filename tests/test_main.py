from pathlib import Path
import importlib.util
import json

from network_simulation.main import load_yaml
from scenarios import scenario_specs


def test_simulated_poc_does_not_require_or_report_manual_baselines(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("poc_main", project_root / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    poc = module.NetworkSimulationPOC(workspace_dir=tmp_path)

    poc.run_poc()

    assert (tmp_path / "reports" / "stage3_analysis.json").is_file()
    analysis = json.loads(
        (tmp_path / "reports" / "stage3_analysis.json").read_text(encoding="utf-8")
    )
    assert analysis["hypothesis_support"]["h3_supported"] is None
    assert analysis["iterations_to_acceptance"]["mean_reduction"] is None
    assert not (tmp_path / "reports" / "stage1_baseline_validation.json").exists()
    assert not list(tmp_path.rglob("*.bicep"))
    report_path = next((tmp_path / "reports").glob("experiment_*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for result in report["results"].values():
        assert result["b0_template"] is None
        assert all(
            iteration["template_path"] == ""
            for iteration in result["b1_iterations"] + result["t1_iterations"]
        )


def test_load_yaml_reads_example_config() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = load_yaml(project_root / "configs" / "experiment.example.yaml")

    assert config["poc"]["name"] == "Controlled Azure network IaC study"
    assert config["study"]["repetitions"] == 1
    assert config["cloud"]["enabled"] is False


def test_scenario_specs_are_loaded_from_yaml_on_demand() -> None:
    scenario_dir = Path(scenario_specs.__file__).resolve().parent / "specs"

    assert scenario_dir.is_dir()
    assert (scenario_dir / "NET-01.yml").exists()

    spec = scenario_specs.get_scenario_spec("NET-01")
    assert spec["name"] == "Basic Virtual Network"
    assert "Resource group exists" in spec["acceptance_criteria"]
    assert "NET-01" in scenario_specs.NET_SCENARIO_SPECS
    assert scenario_specs.NET_SCENARIO_SPECS["NET-01"]["name"] == "Basic Virtual Network"


def test_scenario_extends_are_resolved_recursively() -> None:
    spec = scenario_specs.get_scenario_spec("NET-10")
    merged = scenario_specs.resolve_scenario_context("NET-10")

    assert spec["extends"] == ["NET-08"]
    assert any("All subnets and NSGs exist as in NET-03" in item for item in merged["acceptance_criteria"])
    assert any("Private Endpoints for data services exist" in item for item in merged["acceptance_criteria"])
    assert merged["context_chain"] == ["NET-08", "NET-10"]
