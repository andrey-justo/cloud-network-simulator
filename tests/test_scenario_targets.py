from pathlib import Path

import pytest
import yaml

from network_simulation.configuration import POCConfig
from network_simulation.scenario_targets import TARGETS, scenario_variants
from network_simulation.study import ARMS, ControlledStudyRunner
from network_simulation.ui_worker import preview
from network_simulation.validation.terraform_source import (
    parse_terraform,
    terraform_resources,
)
from network_simulation.validation.terraform_validator import TerraformValidator

ROOT = Path(__file__).resolve().parents[1]
IDS = [f"NET-{number:02}" for number in range(11, 31)]


def runner(**kwargs):
    config = POCConfig.load_yaml(str(ROOT / "configs" / "multicloud-static.yaml"))
    config.study.models = ["fixture"]
    config.validation.run_checkov = False
    return ControlledStudyRunner(workspace_dir=ROOT, config=config, **kwargs)


def test_all_thirty_human_requirements_profile_has_no_execution_blockers():
    config = POCConfig.load_yaml(str(ROOT / "configs" / "human-requirements-static.yaml"))
    study = ControlledStudyRunner(workspace_dir=ROOT, config=config)
    plan = study.plan([f"NET-{number:02}" for number in range(1, 31)])
    assert len(plan["scenarios"]) == 66
    assert len(plan["schedule"]) == 132
    assert len(plan["skipped_variants"]) == 24
    assert plan["execution_blockers"] == []
    assert plan["study"]["assessment_mode"] == "human_review"
    config.cloud.enabled = True
    with pytest.raises(ValueError, match="static-only"):
        study.plan(["NET-01"])


@pytest.mark.parametrize("target", list(TARGETS))
def test_each_target_can_record_unassessed_human_requirements(tmp_path, target, monkeypatch):
    study = runner(llm_clients={"fixture": lambda prompt: "// mocked generation"})
    study.config.study.assessment_mode = "human_review"
    plan = study.plan(["NET-11"])
    key = f"NET-11--{target}"
    monkeypatch.setattr("network_simulation.study.evaluate_structure", lambda *args: pytest.fail("No exact oracle"))
    study._visible = lambda candidate, scenario_id: {"syntax": {"status": "passed"}}
    result = study._trial({
        "scenario_id": key, "model": "fixture", "repetition": 1, "target": target, "arm_order": list(ARMS),
    }, plan["scenarios"][key], tmp_path)
    assert len(study.call_ledger) == 1
    assert all(value["accepted"] is None for value in result["conditions"].values())
    prompt = next(tmp_path.rglob("prompt.txt")).read_text()
    assert "supported_targets" not in prompt and "acceptance_criteria:" not in prompt
    assert "Requirements:\n- " in prompt


@pytest.mark.parametrize("scenario_id", IDS)
def test_high_level_scenarios_are_file_backed_without_resource_graphs(scenario_id):
    path = ROOT / "scenarios" / "specs" / f"{scenario_id}.yml"
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert spec["objective"] and spec["acceptance_criteria"]
    assert "resources" not in spec and "contract" not in spec
    assert (
        spec["supported_targets"] and set(spec["supported_targets"]) <= TARGETS.keys()
    )
    plan = runner().plan([scenario_id])
    for variant in plan["scenarios"].values():
        assert variant["sources"][scenario_id] == path.read_text(encoding="utf-8")
        assert variant["specification"]["objective"] == spec["objective"]
        assert "resources" not in variant["contract"]


def test_matrix_and_execution_guard_do_not_call_models_or_initialize_providers(
    tmp_path,
):
    called = []
    study = runner(llm_clients={"fixture": lambda prompt: called.append(prompt)})
    study.config.experiment.output_directory = str(tmp_path / "results")
    plan = study.plan(IDS)
    assert len(plan["scenarios"]) == 56
    assert len(plan["schedule"]) == 56
    assert len(plan["skipped_variants"]) == 4
    assert plan["execution_blockers"]
    with pytest.raises(ValueError, match="requirements-based acceptance"):
        study.run(IDS)
    assert called == []
    assert not (tmp_path / "results").exists()
    ui = preview(ROOT, {"operation": "new", "config": "configs/multicloud-static.yaml"})
    assert ui["execution_blockers"] and ui["total"] == 112


def test_adding_a_yaml_spec_needs_no_python_catalog_change(tmp_path):
    directory = tmp_path / "scenarios" / "specs"
    directory.mkdir(parents=True)
    source = (ROOT / "scenarios" / "specs" / "NET-11.yml").read_text(encoding="utf-8")
    (directory / "NET-11.yml").write_text(source, encoding="utf-8")
    child = {
        "extends": "NET-11",
        "name": "An additional requirement",
        "objective": "Provide a new high-level requirement from YAML.",
        "family": "addressing",
        "supported_targets": ["azure-bicep", "aws-terraform"],
    }
    (directory / "NET-31.yml").write_text(yaml.safe_dump(child), encoding="utf-8")
    config = POCConfig.load_yaml(str(ROOT / "configs" / "multicloud-static.yaml"))
    study = ControlledStudyRunner(workspace_dir=tmp_path, config=config)
    plan = study.plan(["NET-31"])
    assert len(plan["scenarios"]) == 2
    for scenario in plan["scenarios"].values():
        assert scenario["specification"]["objective"] == child["objective"]
        assert scenario["specification"]["acceptance_criteria"]
        assert set(scenario["sources"]) == {"NET-11", "NET-31"}


@pytest.mark.parametrize("target", list(TARGETS))
def test_generation_and_repair_prompts_never_include_private_contracts(
    tmp_path, target
):
    prompts = []
    responses = iter(["first candidate", "repair candidate", "blind candidate"])

    def client(prompt):
        prompts.append(prompt)
        return next(responses)

    study = runner(llm_clients={"fixture": client})
    plan = study.plan(["NET-11"])
    key = f"NET-11--{target}"
    scenario = plan["scenarios"][key]
    scenario["contract"]["resources"] = {
        "private-oracle-sentinel": {"name": "do-not-reveal"}
    }
    study.config.study.max_iterations = 2
    study._visible = lambda candidate, scenario_id: {"syntax": {"status": "failed"}}
    job = {
        "scenario_id": key,
        "model": "fixture",
        "repetition": 1,
        "target": target,
        "arm_order": list(ARMS),
    }
    study._trial(job, scenario, tmp_path)
    assert len(prompts) == 3
    for prompt in prompts:
        assert scenario["specification"]["objective"] in prompt
        assert "private-oracle-sentinel" not in prompt
        assert "do-not-reveal" not in prompt
        assert "Benchmark requirements" not in prompt
        assert "exact finite contract" not in prompt


def test_legacy_prompt_also_keeps_the_oracle_private(tmp_path):
    prompts = []
    study = runner(
        llm_clients={"fixture": lambda prompt: prompts.append(prompt) or "candidate"}
    )
    plan = study.plan(["NET-01"])
    scenario = plan["scenarios"]["NET-01"]
    scenario["contract"]["private_marker"] = "do-not-reveal"
    study.config.study.max_iterations = 1
    study._visible = lambda candidate, scenario_id: {"syntax": {"status": "failed"}}
    study._trial(
        {
            "scenario_id": "NET-01",
            "model": "fixture",
            "repetition": 1,
            "arm_order": list(ARMS),
        },
        scenario,
        tmp_path,
    )
    assert len(prompts) == 1
    assert "do-not-reveal" not in prompts[0]
    assert "Benchmark requirements" not in prompts[0]


@pytest.mark.parametrize(
    "bad", [[], ["unknown"], [{}], ["aws-terraform", "aws-terraform"]]
)
def test_target_metadata_is_validated(bad):
    spec = {"supported_targets": bad}
    with pytest.raises(ValueError, match="supported_targets"):
        scenario_variants("NET-11", spec, {}, ["aws-terraform"])


def test_resource_graph_specs_and_path_like_ids_are_rejected():
    spec = yaml.safe_load(
        (ROOT / "scenarios" / "specs" / "NET-11.yml").read_text(encoding="utf-8")
    )
    spec["resources"] = {"prescribed": {}}
    with pytest.raises(ValueError, match="resource graph"):
        scenario_variants("NET-11", spec, {}, ["aws-terraform"])
    with pytest.raises(ValueError, match="NET-XX"):
        runner().plan(["../config"])
    with pytest.raises(ValueError, match="NET-XX"):
        runner().plan(["CASE-01"])


@pytest.mark.parametrize(
    "block",
    [
        'module "untrusted" { source = "example.com/module" }',
        'data "external" "run" { program = ["powershell"] }',
        'resource "aws_vpc" "network" { cidr_block = "10.0.0.0/16"\n provisioner "local-exec" { command = "echo forbidden" } }',
        'provider "external" {}',
    ],
)
def test_terraform_rejects_executable_inputs_before_cli(tmp_path, monkeypatch, block):
    source = tmp_path / "main.tf"
    source.write_text(block, encoding="utf-8")
    validator = TerraformValidator(ROOT, executable="must-not-run")
    monkeypatch.setattr(
        validator, "prepare", lambda target: pytest.fail("Must reject before CLI")
    )
    assert validator.validate(source, "aws-terraform")["status"] == "failed"


def test_terraform_source_normalization_and_environment(monkeypatch, tmp_path):
    document = parse_terraform(
        'resource "aws_vpc" "arbitrary_name" { cidr_block = "10.0.0.0/16" }'
    )
    assert (
        terraform_resources(document)["aws_vpc", "arbitrary_name"]["cidr_block"]
        == "10.0.0.0/16"
    )
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "not-a-real-secret")
    monkeypatch.setenv("ARM_CLIENT_SECRET", "not-a-real-secret")
    monkeypatch.setenv("TF_CLI_ARGS", "apply -auto-approve")
    env = TerraformValidator(ROOT)._environment(tmp_path)
    assert (
        not {"AWS_SECRET_ACCESS_KEY", "ARM_CLIENT_SECRET", "TF_CLI_ARGS"} & env.keys()
    )
