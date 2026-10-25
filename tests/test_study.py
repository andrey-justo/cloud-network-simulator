import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from network_simulation.configuration import POCConfig
from network_simulation.configuration.study import StudyConfig
from network_simulation.main import main
from network_simulation.scenario_context import resolve_scenario_context
from network_simulation.study import ARMS, ControlledStudyRunner, summarize_trials
from network_simulation.study_acceptance import (
    ArmDocument,
    evaluate_structure,
    scenario_contract,
)
from network_simulation.study_cloud import AzureStudyBackend

ROOT = Path(__file__).resolve().parents[1]


def contract_template(key):
    contract = scenario_contract(key)

    def materialize(value):
        if isinstance(value, dict):
            if "$subresource" in value:
                target = contract["resources"][value["$subresource"]]
                return (
                    ArmDocument.resource_id(target["type"], target["name"])
                    + f"/{value['collection']}/{value['name']}".lower()
                )
            if "$parameter" in value:
                return f"[parameters('{value['$parameter']}')]"
            if "$resource" in value:
                target = contract["resources"][value["$resource"]]
                if target["name"].startswith(
                    ("benchmark-sql-local", "benchmark-bus-local")
                ):
                    prefix = target["name"].replace("-local", "-{0}", 1)
                    return f"[resourceId('{target['type']}', format('{prefix}', parameters('studySuffix')))]"
                return ArmDocument.resource_id(target["type"], target["name"])
            if "$reference" in value:
                target = contract["resources"][value["$reference"]]
                parts = ", ".join(f"'{part}'" for part in target["name"].split("/"))
                return f"[reference(resourceId('{target['type']}', {parts}), '2023-09-01').{value['path']}]"
            if "$exact" in value:
                return materialize(value["$exact"])
            if "$nonempty" in value:
                return "configured"
            if "$https_url" in value:
                return "https://benchmarkaudit.blob.core.windows.net"
            return {name: materialize(item) for name, item in value.items()}
        if isinstance(value, list):
            return [materialize(item) for item in value]
        return value

    resources = []
    for resource in contract["resources"].values():
        item = materialize(deepcopy(resource))
        if resource["name"].startswith(("benchmark-sql-local", "benchmark-bus-local")):
            pattern = resource["name"].replace("-local", "-{0}", 1)
            item["name"] = f"[format('{pattern}', parameters('studySuffix'))]"
        item["apiVersion"] = "2023-09-01"
        if item["type"].endswith("/virtualNetworks"):
            item["tags"] = {"Experiment": "unit-test"}
        if item["type"].endswith("/publicIPAddresses"):
            item["sku"] = {"name": "Standard"}
        resources.append(item)
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "contentVersion": "1.0.0.0",
        "resources": resources,
        "parameters": deepcopy(contract["parameters"]),
    }


def write_template(tmp_path, template):
    path = tmp_path / "template.json"
    path.write_text(json.dumps(template), encoding="utf-8")
    return path


@pytest.mark.parametrize("key", [f"NET-{number:02}" for number in range(1, 11)])
def test_every_scenario_resolves_and_has_measurable_contract(tmp_path, key):
    resolved = resolve_scenario_context(
        key,
        lambda parent: yaml.safe_load(
            (ROOT / "scenarios" / "specs" / f"{parent}.yml").read_text(encoding="utf-8")
        ),
    )
    contract = scenario_contract(key)
    assert resolved["acceptance_criteria"]
    assert contract["resources"]
    ids = [check["id"] for check in contract["runtime_checks"]]
    assert ids and len(ids) == len(set(ids))
    result = evaluate_structure(write_template(tmp_path, contract_template(key)), key)
    assert result["status"] == "passed", result
    assert result["criteria_passed"] == result["criteria_total"]


@pytest.mark.parametrize(
    "mutation",
    ["missing", "wrong-cidr", "extra-subnet", "missing-tag", "public-nic", "overlap"],
)
def test_basic_contract_rejects_semantic_counterexamples(tmp_path, mutation):
    template = contract_template("NET-01")
    vnet, subnet = template["resources"]
    if mutation == "missing":
        template["resources"].remove(subnet)
    elif mutation == "wrong-cidr":
        subnet["properties"]["addressPrefix"] = "192.168.1.0/24"
    elif mutation == "extra-subnet":
        template["resources"].append(
            {**deepcopy(subnet), "name": "benchmark-vnet/undeclared"}
        )
    elif mutation == "missing-tag":
        vnet["tags"] = {}
    elif mutation == "public-nic":
        template["resources"].append(
            {
                "type": "Microsoft.Network/networkInterfaces",
                "name": "public",
                "properties": {
                    "ipConfigurations": [
                        {"properties": {"publicIPAddress": {"id": "public"}}}
                    ]
                },
            }
        )
    else:
        vnet["properties"]["addressSpace"]["addressPrefixes"].append("10.1.0.0/17")
    result = evaluate_structure(write_template(tmp_path, template), "NET-01")
    assert result["status"] != "passed"


def test_arm_variables_interpolated_child_subnets_and_references(tmp_path):
    template = contract_template("NET-03")
    template["variables"] = {
        "subnetName": "web",
        "nested": "[concat('benchmark-', 'vnet')]",
    }
    template["resources"][0]["name"] = "[variables('nested')]"
    template["resources"][1]["name"] = (
        "[format('{0}/{1}', variables('nested'), variables('subnetName'))]"
    )
    template["resources"][1]["properties"]["networkSecurityGroup"]["id"] = (
        "[resourceId('Microsoft.Network/networkSecurityGroups', 'benchmark-web')]"
    )
    assert (
        evaluate_structure(write_template(tmp_path, template), "NET-03")["status"]
        == "passed"
    )


@pytest.mark.parametrize(
    "expression",
    [
        "[unknown('anything')]",
        "[parameters('missing')]",
        "[variables('loop')]",
        "[format('{0}', 'web').__bad]",
    ],
)
def test_unresolved_arm_expressions_never_count_as_acceptance(tmp_path, expression):
    template = contract_template("NET-01")
    template["variables"] = {"loop": "[variables('loop')]"}
    template["resources"][1]["properties"]["addressPrefix"] = expression
    assert (
        evaluate_structure(write_template(tmp_path, template), "NET-01")["status"]
        != "passed"
    )


def test_extra_allow_rule_fails_even_when_required_rules_remain(tmp_path):
    template = contract_template("NET-03")
    nsg = next(
        resource
        for resource in template["resources"]
        if resource["name"] == "benchmark-app"
    )
    extra = deepcopy(nsg["properties"]["securityRules"][0])
    extra["name"] = "backdoor"
    extra["properties"].update(
        priority=99, sourceAddressPrefix="*", destinationPortRange="*"
    )
    nsg["properties"]["securityRules"].append(extra)
    assert (
        evaluate_structure(write_template(tmp_path, template), "NET-03")["status"]
        == "failed"
    )


def test_private_services_and_firewall_next_hops_are_not_presence_only(tmp_path):
    for key, name, field, value in (
        ("NET-09", "benchmark-bus-local", "publicNetworkAccess", "Enabled"),
        ("NET-10", "benchmark-sql-local", "publicNetworkAccess", "Enabled"),
        ("NET-07", "benchmark-spoke1-routes", "routes", []),
    ):
        template = contract_template(key)
        resource = next(
            item
            for item in template["resources"]
            if (
                item["name"] == name
                or name.startswith(("benchmark-sql-local", "benchmark-bus-local"))
                and item["type"]
                in ("Microsoft.Sql/servers", "Microsoft.ServiceBus/namespaces")
            )
        )
        resource["properties"][field] = value
        assert (
            evaluate_structure(write_template(tmp_path, template), key)["status"]
            == "failed"
        )


def make_runner(
    tmp_path, *, pass_visible=False, client=None, repetitions=1, cloud=None
):
    config = POCConfig()
    config.study.repetitions = repetitions
    config.study.max_iterations = 3
    config.study.bootstrap_samples = 50
    config.validation.run_checkov = False
    config.validation.run_opa_policies = False
    config.experiment.output_directory = str(tmp_path / "results")
    prompts = []

    def fake_client(prompt):
        prompts.append(prompt)
        return "// local mocked generation"

    def compile_template(source, output):
        output.write_text(json.dumps(contract_template("NET-01")), encoding="utf-8")
        return {
            "status": "passed" if pass_visible else "failed",
            "diagnostic": "VISIBLE_DIAGNOSTIC",
        }

    runner = ControlledStudyRunner(
        workspace_dir=ROOT,
        config=config,
        llm_clients={config.llm.model_name: client or fake_client},
        bicep_compiler=SimpleNamespace(
            executable="mock-bicep", validate=compile_template
        ),
        cloud_backend=cloud
        or SimpleNamespace(
            evaluate=lambda *args: pytest.fail("Cloud must stay disabled")
        ),
    )
    return runner, prompts


def test_paired_arms_share_initial_candidate_and_control_feedback_budget(tmp_path):
    runner, prompts = make_runner(tmp_path)
    result = runner.run(["NET-01"])
    assert result["status"] == "completed"
    assert result["physical_model_calls"] == 5
    assert len(prompts) == result["maximum_physical_model_calls"]
    trial = result["trials"][0]
    first_paths = {trial["conditions"][arm]["candidates"][0] for arm in ARMS}
    assert len(first_paths) == 1
    assert trial["conditions"]["one_shot"]["attempts"] == 1
    for arm in ("blind_refinement", "tool_feedback"):
        condition = trial["conditions"][arm]
        assert condition["attempts"] == 3
        assert condition["accepted"] is False
        assert condition["cost_usd"] is None
        for candidate in condition["candidates"][1:]:
            prompt = (Path(candidate) / "prompt.txt").read_text(encoding="utf-8")
            assert ("VISIBLE_DIAGNOSTIC" in prompt) is (arm == "tool_feedback")
            assert "criteria_passed" not in prompt
            assert "Current template:" in prompt
            assert "Scenario:" in prompt
    assert (
        result["summary"]["models"][runner.config.llm.model_name]["conditions"][
            "one_shot"
        ]["nonconverged"]
        == 1
    )


def test_visible_pass_stops_without_using_hidden_acceptance_for_repair(tmp_path):
    runner, prompts = make_runner(tmp_path, pass_visible=True)
    result = runner.run(["NET-01"])
    assert len(prompts) == 1
    assert all(
        condition["accepted"]
        for condition in result["trials"][0]["conditions"].values()
    )
    assert all(
        condition["acceptance_scope"] == "finite_structural_only"
        for condition in result["trials"][0]["conditions"].values()
    )
    assert (
        len(list(Path(result["output_directory"]).rglob("structural-acceptance.json")))
        == 1
    )


def test_failures_remain_in_denominator_and_secrets_are_redacted(tmp_path):
    def broken(_):
        raise RuntimeError("request failed: test-secret")

    runner, _ = make_runner(tmp_path, client=broken)
    runner.config.llm.azure_api_key = "test-secret"
    result = runner.run(["NET-01"])
    assert result["status"] == "completed_with_operational_failures"
    assert result["physical_model_calls"] == 1
    for condition in result["trials"][0]["conditions"].values():
        assert condition["generation_failed"]
        assert not condition["accepted"]
    assert (
        "test-secret"
        not in (Path(result["output_directory"]) / "manifest.json").read_text()
    )
    assert "[REDACTED]" in (Path(result["output_directory"]) / "calls.json").read_text()


def test_token_accounting_and_model_specific_costs_include_shared_candidate_once_physically(
    tmp_path,
):
    class Client:
        def __init__(self):
            self.last_usage = {"input_tokens": 100, "output_tokens": 200}

        def __call__(self, prompt):
            return "// generated"

    runner, _ = make_runner(tmp_path, client=Client())
    runner.config.study.model_prices = {runner.config.llm.model_name: [2, 4]}
    result = runner.run(["NET-01"])
    assert len(runner.call_ledger) == 5
    assert sum(call["cost_usd"] for call in runner.call_ledger) == pytest.approx(0.005)
    conditions = result["trials"][0]["conditions"]
    assert conditions["one_shot"]["cost_usd"] == pytest.approx(0.001)
    assert conditions["tool_feedback"]["cost_usd"] == pytest.approx(0.003)
    assert conditions["tool_feedback"]["usage"]["input_tokens"] == 300


def test_repetitions_and_random_schedule_are_reproducible(tmp_path):
    runner, _ = make_runner(tmp_path, repetitions=3)
    first = runner.plan(["NET-01", "NET-02"])
    assert len(first["schedule"]) == 6
    assert runner.plan(["NET-01", "NET-02"])["schedule"] == first["schedule"]
    runner.config.study.random_seed += 1
    assert runner.plan(["NET-01", "NET-02"])["schedule"] != first["schedule"]
    assert first["paid_execution"] is False
    assert first["maximum_physical_model_calls"] == 30


def test_incomplete_cloud_coverage_cannot_be_accepted(tmp_path):
    cloud = SimpleNamespace(
        evaluate=lambda *args: {
            "deployment_status": "passed",
            "runtime_status": "passed",
            "runtime_checks": [],
        }
    )
    runner, _ = make_runner(tmp_path, pass_visible=True, cloud=cloud)
    runner.config.cloud.enabled = True
    result = runner.run(["NET-01"])
    assert all(
        not item["accepted"] for item in result["trials"][0]["conditions"].values()
    )


def test_cloud_checks_require_exact_ids_not_a_success_shaped_status(tmp_path):
    checks = scenario_contract("NET-01")["runtime_checks"]
    cloud = SimpleNamespace(
        evaluate=lambda *args: {
            "deployment_status": "passed",
            "runtime_status": "passed",
            "runtime_checks": [
                {"id": check["id"], "status": "passed"} for check in checks
            ],
        }
    )
    runner, _ = make_runner(tmp_path, pass_visible=True, cloud=cloud)
    runner.config.cloud.enabled = True
    result = runner.run(["NET-01"])
    assert all(item["accepted"] for item in result["trials"][0]["conditions"].values())


def test_preflight_failure_never_generates(tmp_path):
    runner, prompts = make_runner(tmp_path)
    runner.validator.bicep_compiler.executable = None
    result = runner.run(["NET-01"])
    assert result["status"] == "blocked_preflight"
    assert prompts == []


@pytest.mark.parametrize(
    "setting,value",
    [
        ("repetitions", 0),
        ("max_iterations", True),
        ("bootstrap_samples", -1),
        ("model_prices", {"model": [-1, 2]}),
        ("models", ["same", "same"]),
        ("input_usd_per_million", float("nan")),
    ],
)
def test_invalid_study_protocol_fails_before_execution(setting, value):
    config = StudyConfig()
    setattr(config, setting, value)
    with pytest.raises(ValueError):
        config.validate()


def test_cli_catalog_and_dry_run_do_not_create_clients_or_run_validators(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        "network_simulation.configuration.llm.LLMConfig.create_client",
        lambda _: pytest.fail("No paid calls"),
    )
    assert main(["--workspace", str(ROOT), "--validate-catalog"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert len(catalog["scenarios"]) == 10
    assert (
        main(
            [
                "--workspace",
                str(ROOT),
                "--config",
                "configs\\experiment.example.yaml",
                "--dry-run",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert len(plan["scenarios"]) == 10
    assert plan["cloud"]["enabled"] is False
    assert plan["paid_execution"] is False


def test_bootstrap_does_not_treat_related_scenarios_as_independent(tmp_path):
    runner, _ = make_runner(tmp_path, pass_visible=True)
    records = runner.run(["NET-01"])["trials"]
    records[0]["family"] = "three-tier"
    records.append({**records[0], "scenario_id": "NET-10"})
    summary = summarize_trials(records, seed=1, samples=20)
    comparisons = summary["models"][runner.config.llm.model_name]["paired_comparisons"]
    assert all(item["independent_families"] == 1 for item in comparisons.values())
    assert all(
        item["family_cluster_bootstrap_95_interval"] is None
        for item in comparisons.values()
    )


@pytest.mark.parametrize("key", ["NET-09", "NET-10"])
def test_global_service_names_must_actually_use_per_trial_suffix(tmp_path, key):
    template = contract_template(key)
    for resource in template["resources"]:
        if resource["type"] in (
            "Microsoft.Sql/servers",
            "Microsoft.ServiceBus/namespaces",
        ):
            resource["name"] = (
                "benchmark-sql-local" if key == "NET-10" else "benchmark-bus-local"
            )
    assert (
        evaluate_structure(write_template(tmp_path, template), key)["status"]
        == "failed"
    )


def test_secure_parameter_defaults_and_literal_passwords_are_rejected(tmp_path):
    template = contract_template("NET-10")
    template["parameters"]["sqlAdministratorPassword"]["defaultValue"] = "do-not-embed"
    assert (
        evaluate_structure(write_template(tmp_path, template), "NET-10")["status"]
        == "failed"
    )
    del template["parameters"]["sqlAdministratorPassword"]["defaultValue"]
    server = next(
        item
        for item in template["resources"]
        if item["type"] == "Microsoft.Sql/servers"
    )
    server["properties"]["administratorLoginPassword"] = "do-not-embed"
    assert (
        evaluate_structure(write_template(tmp_path, template), "NET-10")["status"]
        == "failed"
    )


def test_unrequested_resources_and_unwired_gateway_fail_independent_checks(tmp_path):
    template = contract_template("NET-08")
    gateway = next(
        item
        for item in template["resources"]
        if item["type"] == "Microsoft.Network/applicationGateways"
    )
    gateway["properties"]["requestRoutingRules"][0]["properties"]["backendAddressPool"][
        "id"
    ] = "wrong-pool"
    assert (
        evaluate_structure(write_template(tmp_path, template), "NET-08")["status"]
        == "failed"
    )
    template = contract_template("NET-01")
    template["resources"].append(
        {
            "type": "Microsoft.Resources/deploymentScripts",
            "name": "unrequested",
            "properties": {},
        }
    )
    result = evaluate_structure(write_template(tmp_path, template), "NET-01")
    assert (
        next(
            check
            for check in result["checks"]
            if check["id"] == "bounded-resource-types-and-scope"
        )["status"]
        == "failed"
    )


@pytest.mark.parametrize(
    "observed", [None, {}, ["invalid"], [{"id": "wrong", "status": "passed"}]]
)
def test_malformed_cloud_evidence_is_an_operational_failure(tmp_path, observed):
    cloud = SimpleNamespace(
        evaluate=lambda *args: {
            "deployment_status": "passed",
            "runtime_checks": observed,
        }
    )
    runner, _ = make_runner(tmp_path, pass_visible=True, cloud=cloud)
    runner.config.cloud.enabled = True
    result = runner.run(["NET-01"])
    assert result["status"] == "completed_with_operational_failures"
    assert all(
        not item["accepted"] for item in result["trials"][0]["conditions"].values()
    )


def test_cloud_cleanup_failure_surfaces_retained_groups_without_hiding_measurement(
    tmp_path,
):
    checks = scenario_contract("NET-01")["runtime_checks"]
    cloud = SimpleNamespace(
        evaluate=lambda *args: {
            "deployment_status": "passed",
            "cleanup_status": "failed",
            "retained_resource_group": "owned-test-group",
            "cleanup_reason": "access denied",
            "runtime_checks": [
                {"id": check["id"], "status": "passed"} for check in checks
            ],
        }
    )
    runner, _ = make_runner(tmp_path, pass_visible=True, cloud=cloud)
    runner.config.cloud.enabled = True
    result = runner.run(["NET-01"])
    assert result["status"] == "completed_with_operational_failures"
    assert result["retained_resource_groups"] == ["owned-test-group"] * 3
    assert all(item["accepted"] for item in result["trials"][0]["conditions"].values())


def test_missing_runtime_bindings_block_before_paid_calls_and_azure_preflight(
    tmp_path, monkeypatch
):
    runner, prompts = make_runner(tmp_path)
    runner.config.cloud.enabled = True
    runner.cloud = AzureStudyBackend(runner.config.cloud)
    monkeypatch.setattr(
        runner.cloud,
        "preflight",
        lambda _: pytest.fail(
            "Read-only Azure preflight is unnecessary when local bindings already fail"
        ),
    )
    result = runner.run(["NET-01"])
    assert result["status"] == "blocked_preflight"
    assert any("runtime_bindings_file" in error for error in result["preflight_errors"])
    assert prompts == []


def test_cloud_example_covers_every_runtime_check_without_invoking_azure(monkeypatch):
    config = POCConfig.load_yaml(str(ROOT / "configs" / "cloud.example.yaml"))
    monkeypatch.setattr(
        AzureStudyBackend,
        "preflight",
        lambda *_: pytest.fail("Planning must not invoke Azure"),
    )
    plan = ControlledStudyRunner(workspace_dir=ROOT, config=config).plan(
        config.experiment.main_scenarios
    )
    assert plan["cloud_binding_errors"] == []
    assert plan["maximum_cloud_deployments"] == 30
    assert plan["maximum_physical_model_calls"] == 90
    assert "REPLACE_IN_IGNORED_LOCAL_COPY" not in json.dumps(plan)


def test_configuration_round_trips_model_prices_and_resolves_cloud_paths(tmp_path):
    path = tmp_path / "study.yml"
    path.write_text(
        "study:\n  model_prices:\n    gpt-4o: [1.0, 2.0]\n"
        "cloud:\n  parameters_file: parameters.local.json\n  runtime_bindings_file: bindings.local.json\n",
        encoding="utf-8",
    )
    config = POCConfig.load_yaml(str(path))
    assert config.study.model_prices == {"gpt-4o": [1.0, 2.0]}
    assert config.cloud.parameters_file == str(
        (tmp_path / "parameters.local.json").resolve()
    )
    assert config.cloud.runtime_bindings_file == str(
        (tmp_path / "bindings.local.json").resolve()
    )
    saved = tmp_path / "saved.yml"
    config.save_yaml(str(saved))
    assert (
        POCConfig.load_yaml(str(saved)).study.model_prices == config.study.model_prices
    )


def test_responses_usage_and_response_identity_are_recorded_and_reset(monkeypatch):
    import requests

    from network_simulation.azure_responses_client import AzureResponsesClient

    client = AzureResponsesClient(
        endpoint="https://example.test", model="gpt-4o", api_key="local-test"
    )
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "id": "resp-local",
                "model": "gpt-4o-version",
                "status": "completed",
                "output_text": "// bicep",
                "usage": {"input_tokens": 20, "output_tokens": 30},
            },
        ),
    )
    assert client("local mocked prompt") == "// bicep"
    assert client.last_usage == {"input_tokens": 20, "output_tokens": 30}
    assert client.last_response_metadata["id"] == "resp-local"

    def timeout(*args, **kwargs):
        raise requests.Timeout("mock timeout")

    monkeypatch.setattr(requests, "post", timeout)
    with pytest.raises(requests.Timeout):
        client("another local prompt")
    assert client.last_usage is None
    assert client.last_response_metadata == {}


def test_paid_cli_requires_separate_cloud_authorization(monkeypatch):
    monkeypatch.setattr(
        "network_simulation.configuration.llm.LLMConfig.from_env",
        lambda: pytest.fail(
            "Authorization must be checked before credential/client setup"
        ),
    )
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--workspace",
                str(ROOT),
                "--config",
                "configs\\cloud.example.yaml",
                "--execute",
            ]
        )
    assert error.value.code == 2


def test_root_legacy_live_mode_rejects_dry_run_instead_of_making_a_request():
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--mode", "live", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 2
    assert "only valid with --mode study" in completed.stderr


def test_regressions_track_resources_not_only_check_identifiers(tmp_path):
    runner, _ = make_runner(tmp_path, pass_visible=True)
    runner.config.validation.run_checkov = True
    resources = iter(
        (
            "initial-resource",
            "revision-one",
            "revision-two",
            "revision-three",
            "revision-four",
        )
    )
    runner.validator.checkov_validator = SimpleNamespace(
        validate_template=lambda *args, **kwargs: {
            "passed": 0,
            "failed": 1,
            "skipped": 0,
            "total_checks": 1,
            "security_violations": [
                {"check_id": "CKV_TEST", "resource": next(resources)}
            ],
        }
    )
    trial = runner.run(["NET-01"])["trials"][0]
    for arm in ("blind_refinement", "tool_feedback"):
        regression = trial["conditions"][arm]["new_security_check_failures"][0]
        assert regression[0]["check_id"] == "CKV_TEST"
        assert regression[0]["resource"] != "initial-resource"
