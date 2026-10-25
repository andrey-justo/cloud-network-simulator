from pathlib import Path

from network_simulation.main import load_yaml
from scenarios import scenario_specs


def test_load_yaml_reads_example_config() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = load_yaml(project_root / "configs" / "experiment.example.yaml")

    assert config["experiment_name"] == "baseline-proposal-2"
    assert config["runs_per_scenario"] == 3


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
