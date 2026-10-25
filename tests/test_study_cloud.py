"""Local-only study tests. Bindings examples here mirror study_cloud's docstring.

No Azure, paid APIs, ssh-keygen, VM scripts, or external network are invoked.
Scratch directories are created inside the repository and removed per test.
"""

import ast
import json
from pathlib import Path
import shutil
import subprocess
import uuid
from types import SimpleNamespace

import pytest

from network_simulation.study_cloud import (
    AzureStudyBackend, CloudStudyConfig, _DNS_SCRIPT, _EGRESS_SCRIPT, _LISTENER_SCRIPT,
    _HTTP_LISTENER_SCRIPT, _HTTP_SCRIPT,
)


SUB = "11111111-1111-1111-1111-111111111111"
OTHER_SUB = "22222222-2222-2222-2222-222222222222"
EXTERNAL = (
    f"/subscriptions/{SUB}/resourceGroups/external-fixtures/providers/"
    "Microsoft.Compute/virtualMachines/probe"
)


@pytest.fixture
def workspace():
    path = Path(__file__).resolve().parent / f".study-cloud-test-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def machine(data):
    return {"value": [
        {"code": "ComponentStatus/StdOut/succeeded", "message": json.dumps(data)},
        {"code": "ComponentStatus/StdErr/succeeded", "message": ""},
    ]}


def operation(args):
    if args[0] == "ssh-keygen":
        return "keygen"
    words = args[1:]
    for prefix, name in [
        (["account", "show"], "account"),
        (["provider", "show"], "provider"),
        (["rest"], "permissions"),
        (["group", "exists"], "exists"),
        (["group", "create"], "group_create"),
        (["group", "show"], "group_show"),
        (["group", "delete"], "group_delete"),
        (["deployment", "group", "validate"], "validate"),
        (["deployment", "group", "create"], "deploy"),
        (["network", "watcher", "test-connectivity"], "tcp"),
        (["network", "watcher", "show-next-hop"], "route"),
        (["network", "vnet", "subnet", "show"], "subnet"),
        (["network", "vnet", "show"], "vnet"),
        (["network", "nic", "create"], "nic_create"),
        (["network", "nic", "show"], "nic_show"),
        (["network", "nat", "gateway", "show"], "nat"),
        (["network", "firewall", "show"], "firewall"),
        (["network", "public-ip", "show"], "public_ip"),
        (["network", "public-ip", "create"], "public_ip_create"),
        (["network", "private-endpoint", "show"], "private_endpoint"),
        (["resource", "show"], "resource_show"),
        (["vm", "create"], "vm_create"),
        (["vm", "show"], "vm_show"),
        (["vm", "run-command", "invoke"], "run_command"),
    ]:
        if words[:len(prefix)] == prefix:
            return name
    raise AssertionError(f"Unexpected mocked command: {args[:4]}")


def arg(args, flag):
    return args[args.index(flag) + 1]


class FakeAzure:
    def __init__(self, **overrides):
        self.overrides = overrides
        self.calls = []
        self.group = None
        self.tag = None
        self.exists = False
        self.nics = {}
        self.vms = {}
        self.parameter_documents = []

    @property
    def root(self):
        return f"/subscriptions/{SUB}/resourceGroups/{self.group}"

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        assert kwargs["shell"] is False
        assert 0 < kwargs["timeout"] <= 900
        assert kwargs["capture_output"] is True and kwargs["text"] is True
        op = operation(args)
        if op in {"validate", "deploy"} and "--parameters" in args:
            parameter_file = arg(args, "--parameters")
            if parameter_file.startswith("@"):
                self.parameter_documents.append(
                    (op, json.loads(Path(parameter_file[1:]).read_text()))
                )
        if op != "keygen":
            assert args[0] == "az"
            assert arg(args, "--subscription") == SUB
        if op == "group_create":
            self.group = arg(args, "--name")
            self.tag = arg(args, "--tags").split("=", 1)[1]
            self.exists = True
        if op in self.overrides:
            override = self.overrides[op]
            if isinstance(override, Exception):
                raise override
            if callable(override):
                override = override(self, args)
            if isinstance(override, subprocess.CompletedProcess):
                return override
            return subprocess.CompletedProcess(args, 0, json.dumps(override), "")
        if op == "keygen":
            key = Path(arg(args, "-f"))
            key.write_text("FAKE-PRIVATE-KEY-NEVER-LOG")
            key.with_suffix(".pub").write_text("ssh-ed25519 FAKE-PUBLIC")
            data = None
        elif op == "account":
            data = {"id": SUB, "state": "Enabled", "accessToken": "DO-NOT-LOG"}
        elif op == "provider":
            data = "Registered"
        elif op == "permissions":
            data = {"value": [{"actions": ["*"], "notActions": []}]}
        elif op == "exists":
            data = self.exists
        elif op in {"group_create", "group_show"}:
            data = {"name": self.group, "id": self.root,
                    "tags": {"iac-study-run": self.tag}}
        elif op == "group_delete":
            self.exists = False
            return subprocess.CompletedProcess(args, 0, "", "")
        elif op == "validate":
            data = {"properties": {"provisioningState": "Succeeded"}}
        elif op == "deploy":
            data = "Succeeded"
        elif op == "vm_show":
            data = {"id": arg(args, "--ids"), "networkProfile": {"networkInterfaces": [{
                "id": f"/subscriptions/{SUB}/resourceGroups/external-fixtures/"
                "providers/Microsoft.Network/networkInterfaces/external-nic",
            }]}}
        elif op == "vnet":
            data = {"id": self.root + "/providers/Microsoft.Network/virtualNetworks/"
                    + arg(args, "--name"), "location": "eastus"}
        elif op == "subnet":
            data = {"id": self.root + "/providers/Microsoft.Network/virtualNetworks/"
                    + arg(args, "--vnet-name") + "/subnets/" + arg(args, "--name"),
                    "addressPrefix": "10.1.1.0/24"}
        elif op == "nic_create":
            nic_id = self.root + "/providers/Microsoft.Network/networkInterfaces/" + arg(args, "--name")
            self.nics[nic_id] = {
                "id": nic_id, "networkSecurityGroup": None,
                "ipConfigurations": [{
                    "privateIPAddress": arg(args, "--private-ip-address")
                    if "--private-ip-address" in args else f"10.1.{len(self.nics) + 1}.4",
                    "publicIPAddress": {"id": arg(args, "--public-ip-address")}
                    if "--public-ip-address" in args else None,
                    "subnet": {"id": arg(args, "--subnet")},
                }],
            }
            data = {"NewNIC": self.nics[nic_id]}
        elif op == "nic_show":
            nic_id = arg(args, "--ids")
            data = self.nics.get(nic_id, {
                "id": nic_id, "ipConfigurations": [{"subnet": {
                    "id": f"/subscriptions/{SUB}/resourceGroups/external-fixtures/"
                    "providers/Microsoft.Network/virtualNetworks/internet-vantage/subnets/probe",
                }}],
            })
        elif op == "vm_create":
            vm_id = self.root + "/providers/Microsoft.Compute/virtualMachines/" + arg(args, "--name")
            self.vms[vm_id] = arg(args, "--nics")
            data = {"id": vm_id}
        elif op == "tcp":
            data = {"connectionStatus": "Reachable", "probesSent": 3, "probesFailed": 0}
        elif op == "route":
            data = {"nextHopType": "VirtualAppliance", "nextHopIpAddress": "10.1.0.4"}
        elif op in {"nat", "firewall"}:
            ip_ref = {"id": self.root + "/providers/Microsoft.Network/publicIPAddresses/egress"}
            data = {"id": self.root + "/providers/Microsoft.Network/"
                    + ("natGateways/" if op == "nat" else "azureFirewalls/")
                    + arg(args, "--name")}
            if op == "nat":
                data["publicIpAddresses"] = [ip_ref]
            else:
                data["ipConfigurations"] = [{"publicIPAddress": ip_ref}]
        elif op == "public_ip":
            data = {"id": arg(args, "--ids"), "ipAddress": "203.0.113.9"}
        elif op == "public_ip_create":
            assert arg(args, "--sku") == "Standard"
            assert arg(args, "--allocation-method") == "Static"
            data = {"publicIp": {}}
        elif op == "private_endpoint":
            endpoint_id = self.root + "/providers/Microsoft.Network/privateEndpoints/" + arg(args, "--name")
            nic_id = self.root + "/providers/Microsoft.Network/networkInterfaces/endpoint-nic"
            subnet_id = self.root + "/providers/Microsoft.Network/virtualNetworks/benchmark-vnet/subnets/data"
            data = {
                "id": endpoint_id, "subnet": {"id": subnet_id},
                "networkInterfaces": [{"id": nic_id}],
                "privateLinkServiceConnections": [{
                    "privateLinkServiceConnectionState": {"status": "Approved"},
                }],
            }
            self.nics[nic_id] = {
                "id": nic_id, "privateEndpoint": {"id": endpoint_id},
                "ipConfigurations": [{
                    "privateIPAddress": "10.1.3.4", "subnet": {"id": subnet_id},
                }],
            }
        elif op == "resource_show":
            data = {"id": arg(args, "--ids"), "publicNetworkAccess": "Disabled"}
        elif op == "run_command":
            script = arg(args, "--scripts")
            if "listener_ports" in script:
                ports = ast.literal_eval(script.split("for port in ", 1)[1].split(":", 1)[0])
                data = machine({"listener_ports": ports})
            elif '"ready"' in script:
                data = machine({"ready": True})
            elif "api.ipify.org" in script:
                data = machine({"egress_ip": "203.0.113.9"})
            elif "NoRedirect" in script:
                data = machine({"status": 200, "body": f"study-{self.tag}"})
            else:
                data = machine({"addresses": ["10.1.3.4"]})
        else:
            raise AssertionError(op)
        return subprocess.CompletedProcess(args, 0, json.dumps(data), "")


def setup(workspace, *, bindings=None, scenario_id="NET-01", **config):
    template = workspace / "candidate.json"
    template.write_text(json.dumps({
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "contentVersion": "1.0.0.0", "resources": [],
    }))
    binding_file = workspace / "bindings.json"
    binding_file.write_text(json.dumps({scenario_id: bindings if bindings is not None else {
        "sources": {"web": EXTERNAL},
        "source_ips": {"web": "10.1.1.4"},
        "destinations": {"app": "10.1.2.4", "internet": "api.ipify.org",
                         "database": "db.internal"},
        "expected_egress_ip": "203.0.113.9",
        "dns_private_addresses": {"database": ["10.1.3.4"]},
        "route_destinations": {"app": {
            "next_hop_type": "VirtualAppliance", "next_hop_ip": "10.1.0.4",
        }},
    }}))
    options = dict(enabled=True, subscription_id=SUB, location="eastus",
                   runtime_bindings_file=str(binding_file))
    options.update(config)
    return template, CloudStudyConfig(**options)


def check(kind="tcp", **updates):
    value = {"id": kind, "kind": kind, "source": "web",
             "destination": {"egress_ip": "internet", "dns_private": "database"}.get(kind, "app")}
    if kind in {"tcp", "http"}:
        value["port"] = 443
    value.update(updates)
    return value


def evaluate(workspace, fake=None, checks=None, scenario_id="NET-01", **options):
    template, config = setup(workspace, scenario_id=scenario_id, **options)
    fake = fake or FakeAzure()
    result = AzureStudyBackend(config, fake).evaluate(
        template, workspace, scenario_id, checks if checks is not None else [check()]
    )
    assert json.loads(Path(result["evidence_file"]).read_text()) == result
    return result, fake


def test_disabled_has_no_commands_even_with_missing_inputs(workspace):
    fake = FakeAzure()
    result = AzureStudyBackend(CloudStudyConfig(), fake).evaluate(
        workspace / "missing", workspace, "NET-01", [check()]
    )
    assert fake.calls == []
    assert result["deployment_status"] == "disabled"
    assert result["runtime_checks"][0]["status"] == "blocked"


@pytest.mark.parametrize("enabled", ["false", "true", 1, None])
def test_only_boolean_true_enables_cloud(workspace, enabled):
    result, fake = evaluate(workspace, enabled=enabled)
    assert result["deployment_status"] == "disabled"
    assert not fake.calls


@pytest.mark.parametrize("options", [
    {"subscription_id": ""}, {"subscription_id": "not-a-subscription"},
    {"location": ""}, {"location": "eastus;evil"},
    {"resource_group_prefix": "../user-group"},
])
def test_explicit_safe_config_required(workspace, options):
    result, fake = evaluate(workspace, **options)
    assert result["deployment_status"] == "blocked"
    assert not fake.calls


def test_all_runtime_kinds_and_persistent_sanitized_evidence(workspace):
    result, fake = evaluate(workspace, checks=[
        check(kind) for kind in ("tcp", "egress_ip", "dns_private", "route")
    ])
    assert result["deployment_status"] == result["runtime_status"] == "passed"
    assert result["cleanup_status"] == "passed"
    assert [c["status"] for c in result["runtime_checks"]] == ["passed"] * 4
    evidence = Path(result["evidence_file"]).read_text()
    assert "DO-NOT-LOG" not in evidence
    assert "10.1." not in evidence
    assert all(call[0][0] == "az" for call in fake.calls)


@pytest.mark.parametrize("override", [
    {"account": {"id": OTHER_SUB, "state": "Enabled"}},
    {"account": {"id": SUB, "state": "Disabled"}},
    {"provider": "NotRegistered"},
    {"permissions": {"value": []}},
    {"permissions": {"value": [{"actions": ["*"], "notActions": ["Microsoft.Resources/*"]}]}},
    {"permissions": {}},
    {"account": subprocess.CompletedProcess([], 1, "", "SECRET CLI ERROR")},
])
def test_preflight_before_group_creation(workspace, override):
    result, fake = evaluate(workspace, FakeAzure(**override))
    assert result["deployment_status"] == "blocked"
    assert "group_create" not in [operation(a) for a, _ in fake.calls]
    assert "SECRET" not in Path(result["evidence_file"]).read_text()


@pytest.mark.parametrize("scope", [
    "subscriptionDeploymentTemplate.json", "managementGroupDeploymentTemplate.json",
    "tenantDeploymentTemplate.json",
])
def test_reject_non_resource_group_scope(workspace, scope):
    template, config = setup(workspace)
    document = json.loads(template.read_text())
    document["$schema"] = document["$schema"].replace("deploymentTemplate.json", scope)
    template.write_text(json.dumps(document))
    fake = FakeAzure()
    result = AzureStudyBackend(config, fake).evaluate(template, workspace, "NET-01", [check()])
    assert result["reason"] == "unsupported_template_scope"
    assert not fake.calls


@pytest.mark.parametrize("resource", [
    {"type": "Microsoft.Resources/deployments"},
    {"type": "[parameters('resourceType')]"},
    {"type": "Microsoft.Network/virtualNetworks", "scope": "[subscription()]"},
])
def test_reject_unsafe_resource_scopes(workspace, resource):
    template, config = setup(workspace)
    document = json.loads(template.read_text())
    document["resources"] = [resource]
    template.write_text(json.dumps(document))
    fake = FakeAzure()
    result = AzureStudyBackend(config, fake).evaluate(template, workspace, "NET-01", [])
    assert result["deployment_status"] == "blocked"
    assert not fake.calls


@pytest.mark.parametrize("where", ["template", "parameters", "bindings"])
def test_foreign_subscription_ids_rejected_without_cloud_actions(workspace, where):
    template, config = setup(workspace)
    path = {"template": template, "bindings": Path(config.runtime_bindings_file)}.get(where)
    if where == "parameters":
        path = workspace / "parameters.json"
        path.write_text("{}")
        config.parameters_file = str(path)
    document = json.loads(path.read_text())
    document["foreign"] = f"/subscriptions/{OTHER_SUB}/resourceGroups/user"
    path.write_text(json.dumps(document))
    fake = FakeAzure()
    result = AzureStudyBackend(config, fake).evaluate(template, workspace, "NET-01", [])
    assert result["reason"] == "foreign_resource_id"
    assert not fake.calls


def test_secure_parameters_only_passed_by_file_not_dumped(workspace):
    params = workspace / "secure.json"
    params.write_text(json.dumps({"parameters": {"password": {"value": "SUPER-SECRET"}}}))
    result, fake = evaluate(workspace, parameters_file=str(params))
    assert result["deployment_status"] == "passed"
    for args, _ in fake.calls:
        assert "SUPER-SECRET" not in repr(args)
        if operation(args) in {"validate", "deploy"}:
            assert arg(args, "--parameters") == f"@{params.resolve()}"
    assert "SUPER-SECRET" not in Path(result["evidence_file"]).read_text()


def test_existing_group_is_never_created_or_deleted(workspace):
    result, fake = evaluate(workspace, FakeAzure(exists=True))
    assert result["reason"] == "resource_group_not_absent"
    assert result["cleanup_status"] == "not_required"
    assert not any(operation(a) in {"group_create", "group_delete"} for a, _ in fake.calls)


def test_deployment_failure_cleanup_and_errors_do_not_mask_original(workspace):
    fake = FakeAzure(deploy=subprocess.CompletedProcess([], 1, "SECRET", "SECRET"),
                     group_delete=subprocess.TimeoutExpired(["az", "SECRET"], 900))
    result, _ = evaluate(workspace, fake)
    assert result["deployment_status"] == "failed"
    assert result["reason"] == "azure_command_failed"
    assert result["cleanup_status"] == "failed"
    assert result["cleanup_reason"] == "azure_command_timeout"
    assert result["retained_resource_group"] == result["resource_group"]
    assert "SECRET" not in Path(result["evidence_file"]).read_text()


@pytest.mark.parametrize("override", [
    {"validate": {}}, {"validate": {"error": {"message": "SECRET"}}},
    {"deploy": "Failed"}, {"deploy": None},
])
def test_deployment_must_validate_and_succeed(workspace, override):
    result, fake = evaluate(workspace, FakeAzure(**override))
    assert result["deployment_status"] != "passed"
    assert result["runtime_status"] == "blocked"
    assert result["cleanup_status"] == "passed"
    if "validate" in override:
        assert not any(operation(a) == "deploy" for a, _ in fake.calls)


def test_cleanup_disabled_retains_exact_group(workspace):
    result, fake = evaluate(workspace, cleanup=False)
    assert result["cleanup_status"] == "retained"
    assert result["retained_resource_group"] == result["resource_group"]
    assert not any(operation(a) == "group_delete" for a, _ in fake.calls)


@pytest.mark.parametrize("change", ["tag", "id", "name"])
def test_cleanup_requires_exact_identity_and_per_run_tag(workspace, change):
    def wrong_owner(fake, args):
        value = {"id": fake.root, "name": fake.group, "tags": {"iac-study-run": fake.tag}}
        if change == "tag":
            value["tags"] = {"iac-study-run": "someone-else"}
        else:
            value[change] = "someone-else"
        return value
    result, fake = evaluate(workspace, FakeAzure(group_show=wrong_owner))
    assert result["cleanup_status"] == "failed"
    assert result["deployment_status"] == "passed"
    assert not any(operation(a) == "group_delete" for a, _ in fake.calls)


def test_timed_out_group_creation_cleanup_checks_tag(workspace):
    result, fake = evaluate(workspace, FakeAzure(
        group_create=subprocess.TimeoutExpired(["az"], 180)
    ))
    assert result["reason"] == "azure_command_timeout"
    assert result["cleanup_status"] == "passed"
    assert any(operation(a) == "group_delete" for a, _ in fake.calls)


def test_delete_success_without_confirmed_absence_is_cleanup_failure(workspace):
    def still_exists(fake, args):
        return fake.group is not None
    result, _ = evaluate(workspace, FakeAzure(exists=still_exists))
    assert result["cleanup_status"] == "failed"
    assert result["cleanup_reason"] == "cleanup_not_confirmed"


@pytest.mark.parametrize("probe", [
    {}, None, {"connectionStatus": "Unknown"},
    {"connectionStatus": "Reachable"},
    {"connectionStatus": "Reachable", "probesSent": 1, "probesFailed": 1},
    {"connectionStatus": "Unreachable", "probesSent": 3, "probesFailed": 3},
    subprocess.CompletedProcess([], 1, "", "timed out SECRET"),
    subprocess.CompletedProcess([], 0, "NOT-JSON SECRET", ""),
    subprocess.TimeoutExpired(["az"], 180),
])
def test_tcp_infrastructure_failure_never_means_secure_block(workspace, probe):
    result, _ = evaluate(workspace, FakeAzure(tcp=probe), checks=[check(expected=False)])
    assert result["runtime_checks"][0]["status"] == "blocked"
    assert "SECRET" not in Path(result["evidence_file"]).read_text()


def test_tcp_explicit_nsg_deny_can_pass_expected_false(workspace):
    deny = {"connectionStatus": "Unreachable", "probesSent": 3, "probesFailed": 3,
            "hops": [{"issues": [{"type": "NetworkSecurityRule",
                                 "origin": "Outbound", "severity": "Error"}]}]}
    result, _ = evaluate(workspace, FakeAzure(tcp=deny), checks=[check(expected=False)])
    assert result["runtime_status"] == "passed"


def test_valid_unexpected_observation_is_failed_not_blocked(workspace):
    result, _ = evaluate(workspace, checks=[check(expected=False)])
    assert result["runtime_checks"][0]["status"] == "failed"
    assert result["runtime_status"] == "failed"


@pytest.mark.parametrize("entry", [
    None, {}, check(id=""), check(kind="shell"), check(port=True), check(port=0),
    check(port=65536), check(expected="false"), check(source=[]),
])
def test_every_malformed_check_gets_blocked_result(workspace, entry):
    result, _ = evaluate(workspace, checks=[entry])
    assert len(result["runtime_checks"]) == 1
    assert result["runtime_checks"][0]["status"] == "blocked"


def test_duplicate_ids_are_all_blocked_and_checks_continue(workspace):
    result, _ = evaluate(workspace, checks=[check(), check(), check("route")])
    assert [c["status"] for c in result["runtime_checks"]] == ["blocked", "blocked", "passed"]


@pytest.mark.parametrize("entry", [
    check(destination="absent"), check(source="absent"),
])
def test_missing_roles_never_pass(workspace, entry):
    result, _ = evaluate(workspace, checks=[entry])
    assert result["runtime_checks"][0]["status"] == "blocked"


@pytest.mark.parametrize("value", [
    None, {}, {"value": []},
    machine({"egress_ip": "not-ip"}),
    {"value": [{"code": "ComponentStatus/StdOut/succeeded", "message": "not-json"}]},
    {"value": [{"code": "ComponentStatus/StdOut/failed", "message": '{"egress_ip":"203.0.113.9"}'}]},
    {"value": [{"code": "ComponentStatus/StdOut/succeeded",
                "message": '{"egress_ip":"203.0.113.9"}'},
               {"code": "ComponentStatus/StdErr/succeeded", "message": "Traceback secret"}]},
])
def test_machine_probe_requires_clean_exact_json(workspace, value):
    result, _ = evaluate(workspace, FakeAzure(run_command=value),
                         checks=[check("egress_ip", expected=False)])
    assert result["runtime_checks"][0]["status"] == "blocked"


@pytest.mark.parametrize("value", [
    {}, {"addresses": []}, {"addresses": ["not-ip"]}, {"addresses": None},
])
def test_dns_failure_is_not_evidence_of_secure_dns(workspace, value):
    result, _ = evaluate(workspace, FakeAzure(run_command=machine(value)),
                         checks=[check("dns_private", expected=False)])
    assert result["runtime_checks"][0]["status"] == "blocked"


def test_dns_public_resolution_is_valid_negative_observation(workspace):
    result, _ = evaluate(workspace, FakeAzure(
        run_command=machine({"addresses": ["8.8.8.8"]})
    ), checks=[check("dns_private", expected=False)])
    assert result["runtime_status"] == "passed"


@pytest.mark.parametrize("route", [
    {}, {"nextHopType": "None"}, {"nextHopType": "Bogus", "nextHopIpAddress": ""},
    {"nextHopType": "VirtualAppliance", "nextHopIpAddress": ""},
])
def test_route_never_defaults_to_success(workspace, route):
    result, _ = evaluate(workspace, FakeAzure(route=route),
                         checks=[check("route", expected=False)])
    assert result["runtime_status"] == "blocked"


def fixture_bindings():
    return {
        "sources": {
            "web": {"vnet": "benchmark-vnet", "subnet": "web", "vm_size": "Standard_B1s"},
            "app": {"vnet": "benchmark-vnet", "subnet": "app",
                    "vm_size": "Standard_B1s", "location": "eastus"},
            "external": EXTERNAL,
        },
        "destinations": {"app": {"source": "app", "listener_ports": [443, 8443]}},
    }


def test_candidate_fixtures_are_owned_private_and_use_exact_created_ids(workspace):
    result, fake = evaluate(workspace, bindings=fixture_bindings())
    assert result["runtime_status"] == "passed"
    assert len(fake.vms) == 2
    for vm_id, nic_id in fake.vms.items():
        assert vm_id.startswith(fake.root + "/")
        assert nic_id.startswith(fake.root + "/")
    for args, _ in fake.calls:
        op = operation(args)
        if op in {"vnet", "subnet", "nic_create", "vm_create"}:
            assert arg(args, "--resource-group") == fake.group
        if op == "nic_create":
            assert "--network-security-group" not in args
            assert "--public-ip-address" not in args
        if op == "vm_create":
            assert arg(args, "--image") == "Ubuntu2204"
            assert "--nsg" not in args and "--public-ip-address" not in args
            assert "--nics" in args
        if op == "tcp":
            assert arg(args, "--source-resource") in fake.vms
            assert arg(args, "--dest-address") == "10.1.2.4"
    assert list(workspace.glob("study-cloud-*/probe_ed25519")) == []
    assert len(list(workspace.glob("study-cloud-*/probe_ed25519.pub"))) == 1
    assert "FAKE-PRIVATE-KEY" not in Path(result["evidence_file"]).read_text()
    assert sum(operation(a) == "keygen" for a, _ in fake.calls) == 1


def test_no_listeners_without_explicit_destination_ports(workspace):
    bindings = fixture_bindings()
    bindings["destinations"]["app"].pop("listener_ports")
    result, fake = evaluate(workspace, bindings=bindings)
    assert result["runtime_status"] == "passed"
    assert not any(operation(a) == "run_command" and "listener_ports" in arg(a, "--scripts")
                   for a, _ in fake.calls)


@pytest.mark.parametrize("override", [
    {"vnet": {"id": f"/subscriptions/{OTHER_SUB}/resourceGroups/user", "location": "eastus"}},
    {"subnet": {"id": f"/subscriptions/{SUB}/resourceGroups/existing/subnet"}},
    {"vm_create": {"id": EXTERNAL}},
    {"vm_create": subprocess.CompletedProcess([], 1, "", "agent unavailable SECRET")},
    {"run_command": machine({"ready": False})},
    {"run_command": subprocess.TimeoutExpired(["az"], 180)},
    {"keygen": FileNotFoundError("ssh-keygen")},
])
def test_fixture_failures_block_not_securely_deny(workspace, override):
    result, fake = evaluate(workspace, FakeAzure(**override), bindings=fixture_bindings(),
                            checks=[check(expected=False)])
    assert result["deployment_status"] == "passed"
    assert result["runtime_status"] == "blocked"
    assert result["cleanup_status"] == "passed"
    assert not any(operation(a) == "tcp" for a, _ in fake.calls)


@pytest.mark.parametrize("bad_nic", ["public", "nsg", "foreign_subnet"])
def test_nic_must_inherit_candidate_subnet_without_public_ip_or_nsg(workspace, bad_nic):
    def changed(fake, args):
        nic = fake.nics[arg(args, "--ids")]
        if bad_nic == "public":
            nic["ipConfigurations"][0]["publicIPAddress"] = {"id": "public"}
        elif bad_nic == "nsg":
            nic["networkSecurityGroup"] = {"id": "override"}
        else:
            nic["ipConfigurations"][0]["subnet"]["id"] = "foreign"
        return nic
    result, fake = evaluate(workspace, FakeAzure(nic_show=changed), bindings=fixture_bindings())
    assert result["runtime_status"] == "blocked"
    assert not fake.vms


def test_listener_failure_blocks_destination_even_when_source_ready(workspace):
    def listener_failure(fake, args):
        if "listener_ports" in arg(args, "--scripts"):
            return machine({"listener_ports": []})
        return machine({"ready": True})
    result, _ = evaluate(workspace, FakeAzure(run_command=listener_failure),
                         bindings=fixture_bindings())
    assert result["runtime_checks"][0]["reason"] == "fixture_listener_not_ready"
    assert result["runtime_status"] == "blocked"


@pytest.mark.parametrize("spec", [
    {"vnet": "../outside", "subnet": "web", "vm_size": "Standard_B1s"},
    {"vnet": "benchmark-vnet", "subnet": "web", "vm_size": "Standard_B1s", "location": "westus"},
])
def test_fixture_names_and_location_are_validated(workspace, spec):
    bindings = fixture_bindings()
    bindings["sources"]["web"] = spec
    result, _ = evaluate(workspace, bindings=bindings)
    assert result["runtime_status"] == "blocked"


def test_external_vm_can_be_explicit_vantage_point_but_no_listener_install(workspace):
    bindings = {"sources": {"web": EXTERNAL}, "source_ips": {"web": "10.2.0.4"},
                "destinations": {"app": {"source": "web", "listener_ports": [443]}}}
    result, fake = evaluate(workspace, bindings=bindings)
    assert result["runtime_status"] == "blocked"
    assert result["runtime_checks"][0]["reason"] == "listeners_require_owned_fixture"
    assert not any(operation(a) == "run_command" for a, _ in fake.calls)


def test_explicit_address_object_supported(workspace):
    bindings = {"sources": {"web": EXTERNAL},
                "destinations": {"app": {"address": "10.1.2.4"}}}
    result, _ = evaluate(workspace, bindings=bindings)
    assert result["runtime_status"] == "passed"


def test_no_runtime_checks_is_not_claimed_runtime_success(workspace):
    result, _ = evaluate(workspace, checks=[])
    assert result["deployment_status"] == "passed"
    assert result["runtime_status"] == "not_requested"


def test_fixed_scripts_compile_without_execution():
    for script in (_DNS_SCRIPT.replace("HOST", repr("db.internal")),
                   _EGRESS_SCRIPT, _LISTENER_SCRIPT.replace("PORTS", "[443, 8443]"),
                   _HTTP_LISTENER_SCRIPT.replace("PORTS", "[80]").replace(
                       "BODY_LENGTH", "38").replace("BODY_MARKER", "study-example"),
                   _HTTP_SCRIPT.replace("URL", repr("http://10.1.0.4:80/"))):
        source = script.split("\n", 1)[1].rsplit("\nPY", 1)[0]
        tree = ast.parse(source)
        compile(tree, "<fixed-study-script>", "exec")
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "code" for target in node.targets
            ):
                compile(ast.literal_eval(node.value), "<fixed-listener>", "exec")


@pytest.mark.parametrize("with_file", [False, True])
def test_unique_study_suffix_override_is_identical_for_validate_create(workspace, with_file):
    template, config = setup(workspace)
    document = json.loads(template.read_text())
    document["parameters"] = {"studySuffix": {"type": "string", "defaultValue": "local"}}
    template.write_text(json.dumps(document))
    if with_file:
        params = workspace / "parameters.json"
        params.write_text(json.dumps({"parameters": {
            "studySuffix": {"value": "local"}, "password": {"value": "SECRET"},
        }}))
        config.parameters_file = str(params)
    fake = FakeAzure()
    result = AzureStudyBackend(config, fake).evaluate(template, workspace, "NET-01", [])
    parameter_args = [
        a[a.index("--parameters") + 1:a.index("--subscription")]
        for a, _ in fake.calls if operation(a) in {"validate", "deploy"}
    ]
    # create adds a query after parameters; compare only parameter values.
    parameter_args = [a[:a.index("--query")] if "--query" in a else a for a in parameter_args]
    assert parameter_args[0] == parameter_args[1]
    assert parameter_args[0][-1] == f"studySuffix={result['study_suffix']}"
    if with_file:
        assert parameter_args[0][0] == f"@{params.resolve()}"
    assert result["resource_group"].endswith(result["study_suffix"])
    assert "SECRET" not in Path(result["evidence_file"]).read_text()


def test_destination_substitutions_resolve_exact_candidate(workspace):
    bindings = {"sources": {"web": EXTERNAL}, "destinations": {
        "app": {"address": "benchmark-sql-{study_suffix}.database.windows.net"},
        "group": "{resource_group}.example.org",
    }}
    result, fake = evaluate(workspace, bindings=bindings)
    args = next(a for a, _ in fake.calls if operation(a) == "tcp")
    assert arg(args, "--dest-address") == f"benchmark-sql-{result['study_suffix']}.database.windows.net"
    assert result["runtime_status"] == "passed"


@pytest.mark.parametrize("resource_type", ["nat_gateway", "firewall"])
def test_expected_egress_ip_is_resolved_from_owned_candidate_resource(workspace, resource_type):
    bindings = {"sources": {"web": EXTERNAL}, "destinations": {"internet": "api.ipify.org"},
                "expected_egress_ip": {"resource_type": resource_type, "name": "benchmark-egress"}}
    result, fake = evaluate(workspace, bindings=bindings, checks=[check("egress_ip")])
    assert result["runtime_status"] == "passed"
    args = next(a for a, _ in fake.calls if operation(a) in {"nat", "firewall"})
    assert arg(args, "--resource-group") == result["resource_group"]


@pytest.mark.parametrize("value", [
    {"id": EXTERNAL, "publicIpAddresses": []},
    None, {},
])
def test_invalid_candidate_egress_identity_blocks(workspace, value):
    bindings = {"sources": {"web": EXTERNAL}, "destinations": {"internet": "api.ipify.org"},
                "expected_egress_ip": {"resource_type": "nat_gateway", "name": "benchmark-nat"}}
    result, _ = evaluate(workspace, FakeAzure(nat=value), bindings=bindings,
                         checks=[check("egress_ip", expected=False)])
    assert result["runtime_status"] == "blocked"


def test_route_check_type_can_supply_expected_binding_type(workspace):
    bindings = {"sources": {"web": EXTERNAL}, "source_ips": {"web": "10.1.1.4"},
                "destinations": {"app": "10.1.2.4"},
                "route_destinations": {"app": {"next_hop_ip": "10.1.0.4"}}}
    result, _ = evaluate(workspace, bindings=bindings, checks=[
        check("route", expected_next_hop_type="VirtualAppliance")
    ])
    assert result["runtime_status"] == "passed"


def http_bindings():
    value = fixture_bindings()
    value["sources"].pop("app")
    value["destinations"] = {
        "web": {"source": "web", "listener_ports": [80],
                "expected_body": "study-{study_suffix}"},
        "gateway": {"address": "gateway-{study_suffix}.example.org",
                    "expected_body": "study-{study_suffix}"},
    }
    return value


def test_http_external_gateway_requires_exact_fixture_marker(workspace):
    result, fake = evaluate(workspace, bindings=http_bindings(), checks=[
        check("http", id="external-gateway-http", source="external", destination="gateway", port=80)
    ])
    assert result["runtime_status"] == "passed"
    scripts = [arg(a, "--scripts") for a, _ in fake.calls if operation(a) == "run_command"]
    assert any(f"study-{result['study_suffix']}" in script and "HTTP/1.0 200 OK" in script
               for script in scripts)
    http_args = next(a for a, _ in fake.calls if operation(a) == "run_command"
                     and "NoRedirect" in arg(a, "--scripts"))
    assert arg(http_args, "--ids") == EXTERNAL
    assert f"http://gateway-{result['study_suffix']}.example.org:80/" in arg(http_args, "--scripts")


def test_http_body_mismatch_fails_not_passes(workspace):
    def wrong_http(fake, args):
        if "NoRedirect" in arg(args, "--scripts"):
            return machine({"status": 200, "body": "unrelated-server"})
        if "listener_ports" in arg(args, "--scripts"):
            return machine({"listener_ports": [80]})
        return machine({"ready": True})
    result, _ = evaluate(workspace, FakeAzure(run_command=wrong_http),
                         bindings=http_bindings(), checks=[
                             check("http", source="external", destination="gateway", port=80)
                         ])
    assert result["runtime_status"] == "failed"


def test_http_blocked_when_required_web_listener_failed(workspace):
    def broken_listener(fake, args):
        if "listener_ports" in arg(args, "--scripts"):
            return machine({"listener_ports": []})
        if "NoRedirect" in arg(args, "--scripts"):
            pytest.fail("Do not probe a gateway whose candidate listener fixture failed")
        return machine({"ready": True})
    result, _ = evaluate(workspace, FakeAzure(run_command=broken_listener),
                         bindings=http_bindings(), checks=[
                             check("http", source="external", destination="gateway", port=80)
                         ])
    assert result["runtime_status"] == "blocked"
    assert result["runtime_checks"][0]["reason"] == "http_listener_fixture_not_ready"


def test_http_destination_can_resolve_owned_gateway_public_ip(workspace):
    bindings = http_bindings()
    bindings["destinations"]["gateway"].pop("address")
    bindings["destinations"]["gateway"]["public_ip"] = "benchmark-gateway-pip"
    result, fake = evaluate(workspace, bindings=bindings, checks=[
        check("http", source="external", destination="gateway", port=80)
    ])
    assert result["runtime_status"] == "passed"
    args = next(a for a, _ in fake.calls if operation(a) == "run_command"
                and "NoRedirect" in arg(a, "--scripts"))
    assert "http://203.0.113.9:80/" in arg(args, "--scripts")


@pytest.mark.parametrize("observed", [
    {}, {"status": 500, "body": "error"}, {"status": 200, "body": None},
    {"status": True, "body": "anything"},
])
def test_http_malformed_or_error_result_cannot_securely_block(workspace, observed):
    bindings = {"sources": {"external": EXTERNAL}, "destinations": {
        "gateway": {"address": "gateway.example.org", "expected_body": "study-{study_suffix}"},
    }}
    result, _ = evaluate(workspace, FakeAzure(run_command=machine(observed)),
                         bindings=bindings, checks=[
                             check("http", source="external", destination="gateway",
                                   port=80, expected=False)
                         ])
    assert result["runtime_status"] == "blocked"


@pytest.mark.parametrize("source", ["missing", "web"])
def test_http_missing_external_fixture_or_internal_substitute_is_blocked(workspace, source):
    result, _ = evaluate(workspace, bindings=http_bindings(), checks=[
        check("http", source=source, destination="gateway", port=80)
    ])
    assert result["runtime_status"] == "blocked"


@pytest.mark.parametrize("subnet", ["gateway", "ApplicationGatewaySubnet", "AzureFirewallSubnet"])
def test_no_probe_vm_in_dedicated_gateway_or_firewall_subnet(workspace, subnet):
    bindings = fixture_bindings()
    bindings["sources"] = {"web": {
        "vnet": "benchmark-hub", "subnet": subnet, "vm_size": "Standard_B1s",
    }}
    result, fake = evaluate(workspace, bindings=bindings)
    assert result["runtime_status"] == "blocked"
    assert not any(operation(a) in {"nic_create", "vm_create"} for a, _ in fake.calls)


def public_web_bindings():
    return {
        "sources": {
            "web": {"vnet": "benchmark-vnet", "subnet": "web",
                    "vm_size": "Standard_B1s", "public_ip": True},
            "external": EXTERNAL,
        },
        "destinations": {
            "web_public": {"source": "web", "address_kind": "public", "listener_ports": [80]},
            "web_private": {"source": "web"},
        },
    }


def test_net03_public_web_fixture_inherits_nsg_and_has_explicit_public_destination(workspace):
    result, fake = evaluate(workspace, bindings=public_web_bindings(), scenario_id="NET-03",
                            checks=[
                                check(source="external", destination="web_public", port=80),
                                check(id="private-web", destination="web_private", port=80),
                            ])
    assert result["runtime_status"] == "passed"
    assert [c["status"] for c in result["runtime_checks"]] == ["passed", "passed"]
    create = next(a for a, _ in fake.calls if operation(a) == "public_ip_create")
    assert arg(create, "--resource-group") == result["resource_group"]
    nic_args = next(a for a, _ in fake.calls if operation(a) == "nic_create")
    assert arg(nic_args, "--public-ip-address").startswith(fake.root + "/")
    assert "--network-security-group" not in nic_args
    tcp_args = [a for a, _ in fake.calls if operation(a) == "tcp"]
    assert arg(tcp_args[0], "--dest-address") == "203.0.113.9"
    assert arg(tcp_args[1], "--dest-address") == "10.1.1.4"


@pytest.mark.parametrize("scenario_id,role,subnet", [
    ("NET-01", "web", "web"), ("NET-03", "app", "web"),
    ("NET-03", "web", "app"), ("NET-10", "web", "web"),
])
def test_public_fixture_rejected_outside_exact_net03_web_contract(
    workspace, scenario_id, role, subnet,
):
    bindings = public_web_bindings()
    spec = bindings["sources"].pop("web")
    spec["subnet"] = subnet
    bindings["sources"][role] = spec
    result, fake = evaluate(workspace, scenario_id=scenario_id, bindings=bindings,
                            checks=[check(source=role, destination="web_public", port=80)])
    assert result["runtime_status"] == "blocked"
    assert not any(operation(a) in {"public_ip_create", "nic_create", "vm_create"}
                   for a, _ in fake.calls)


def test_private_fixture_cannot_be_resolved_as_public_endpoint(workspace):
    bindings = fixture_bindings()
    bindings["destinations"] = {"web": {"source": "web", "address_kind": "public"}}
    result, _ = evaluate(workspace, bindings=bindings, checks=[check(destination="web")])
    assert result["runtime_status"] == "blocked"


def test_external_vantage_cannot_be_attached_to_candidate_vnet(workspace):
    def candidate_network(fake, args):
        return {"id": arg(args, "--ids"), "ipConfigurations": [{"subnet": {
            "id": fake.root + "/providers/Microsoft.Network/virtualNetworks/benchmark-vnet/subnets/web",
        }}]}
    result, fake = evaluate(workspace, FakeAzure(nic_show=candidate_network))
    assert result["runtime_status"] == "blocked"
    assert result["runtime_checks"][0]["reason"] == "external_source_must_be_outside_candidate_network"
    assert not any(operation(a) == "tcp" for a, _ in fake.calls)


def test_external_vantage_without_network_metadata_is_blocked(workspace):
    result, _ = evaluate(workspace, FakeAzure(vm_show={"id": EXTERNAL}))
    assert result["runtime_status"] == "blocked"
    assert result["runtime_checks"][0]["reason"] == "external_source_network_not_verified"


def test_duplicate_json_output_keys_cannot_count_as_a_probe(workspace):
    response = subprocess.CompletedProcess(
        [], 0,
        '{"connectionStatus":"Unreachable","connectionStatus":"Reachable",'
        '"probesSent":3,"probesFailed":0}',
        "",
    )
    result, _ = evaluate(workspace, FakeAzure(tcp=response))
    assert result["runtime_status"] == "blocked"


def test_malformed_id_is_sanitized_and_still_has_blocked_result(workspace):
    result, _ = evaluate(workspace, checks=[check(id={"password": "NOT-AN-ID"})])
    assert result["runtime_checks"][0]["id"] is None
    assert result["runtime_checks"][0]["status"] == "blocked"
    assert "NOT-AN-ID" not in Path(result["evidence_file"]).read_text()


def test_untrusted_reserved_binding_fields_never_become_evidence(workspace):
    bindings = {"sources": {"web": EXTERNAL}, "destinations": {"internet": "api.ipify.org"},
                "expected_egress_ip": "203.0.113.9", "_egress_error": "SECRET-NEVER-LOG"}
    result, _ = evaluate(workspace, bindings=bindings, checks=[check("egress_ip")])
    assert result["runtime_status"] == "passed"
    assert "SECRET-NEVER-LOG" not in Path(result["evidence_file"]).read_text()


def test_numeric_ip_output_is_not_a_valid_machine_ip(workspace):
    result, _ = evaluate(workspace, FakeAzure(run_command=machine({"egress_ip": 3405803785})),
                         checks=[check("egress_ip", expected=False)])
    assert result["runtime_status"] == "blocked"


def test_fixture_health_requires_boolean_true_not_numeric_one(workspace):
    result, _ = evaluate(workspace, FakeAzure(run_command=machine({"ready": 1})),
                         bindings=fixture_bindings())
    assert result["runtime_status"] == "blocked"


def test_public_preflight_reads_capabilities_and_external_sources_without_writes(workspace):
    _, config = setup(workspace)
    fake = FakeAzure()
    before = sorted(p.name for p in workspace.rglob("*"))
    backend = AzureStudyBackend(config, fake)
    assert fake.calls == []  # Construction/planning does not trigger checks.
    assert backend.preflight(["NET-01"]) == []
    assert sorted(p.name for p in workspace.rglob("*")) == before
    assert {operation(a) for a, _ in fake.calls} == {
        "account", "provider", "permissions", "vm_show", "nic_show",
    }
    assert fake.group is None


def test_public_preflight_fixtures_never_provisions_or_generates_keys(workspace):
    _, config = setup(workspace, bindings=http_bindings())
    fake = FakeAzure()
    assert AzureStudyBackend(config, fake).preflight(["NET-01"]) == []
    assert all(operation(a) in {"account", "provider", "permissions", "vm_show", "nic_show"}
               for a, _ in fake.calls)
    assert not list(workspace.glob("study-cloud-*"))


def test_public_preflight_disabled_is_local_only(workspace):
    fake = FakeAzure()
    assert AzureStudyBackend(CloudStudyConfig(), fake).preflight(["NET-01"]) == ["cloud_disabled"]
    assert fake.calls == []
    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize("options", [
    {"subscription_id": ""}, {"location": ""}, {"runtime_bindings_file": None},
])
def test_public_preflight_rejects_incomplete_config_before_cli(workspace, options):
    _, config = setup(workspace, **options)
    fake = FakeAzure()
    reasons = AzureStudyBackend(config, fake).preflight(["NET-01"])
    assert reasons
    assert fake.calls == []


@pytest.mark.parametrize("scenarios", [[], ["NET-01", "NET-01"], [None], "NET-01"])
def test_public_preflight_requires_unique_nonempty_scenario_ids(workspace, scenarios):
    _, config = setup(workspace)
    fake = FakeAzure()
    assert AzureStudyBackend(config, fake).preflight(scenarios) == ["invalid_scenario_ids"]
    assert not fake.calls


def test_public_preflight_reports_each_scenario_missing_bindings(workspace):
    _, config = setup(workspace)
    fake = FakeAzure()
    reasons = AzureStudyBackend(config, fake).preflight(["NET-02", "NET-03"])
    assert reasons == [
        "NET-02:runtime_bindings_missing", "NET-03:runtime_bindings_missing",
    ]
    assert not fake.calls


@pytest.mark.parametrize("bindings", [
    {}, {"sources": {}, "destinations": {"app": "10.1.0.4"}},
    {"sources": {"web": EXTERNAL}, "destinations": {}},
    {"sources": {"web": EXTERNAL}, "destinations": {"app": {"source": "missing"}}},
    {"sources": {"web": EXTERNAL}, "destinations": {"app": {"source": "web"}}},
    {"sources": {"web": EXTERNAL},
     "destinations": {"app": {"source": "web", "address_kind": "public"}}},
    {"sources": {"web": EXTERNAL}, "destinations": {"app": "10.1.0.4"},
     "dns_private_addresses": {"app": []}},
    {"sources": {"web": EXTERNAL}, "destinations": {"app": "10.1.0.4"},
     "route_destinations": {"app": {"next_hop_type": "VirtualAppliance"}}},
])
def test_public_preflight_rejects_incomplete_declared_runtime_bindings(workspace, bindings):
    _, config = setup(workspace, bindings=bindings)
    fake = FakeAzure()
    reasons = AzureStudyBackend(config, fake).preflight(["NET-01"])
    assert reasons and all(reason.startswith("NET-01:") for reason in reasons)
    assert not fake.calls


@pytest.mark.parametrize("failure", [
    FileNotFoundError("SECRET path"),
    subprocess.TimeoutExpired(["az", "SECRET"], 180),
    subprocess.CompletedProcess([], 1, "SECRET token", "SECRET login error"),
])
def test_public_preflight_cli_or_login_failure_returns_sanitized_reasons(workspace, failure):
    _, config = setup(workspace)
    fake = FakeAzure(account=failure)
    reasons = AzureStudyBackend(config, fake).preflight(["NET-01"])
    assert reasons
    assert "SECRET" not in repr(reasons)
    assert {operation(a) for a, _ in fake.calls} == {"account"}
    assert not list(workspace.glob("study-cloud-*"))


def test_public_preflight_checks_multiple_scenarios_once_and_deduplicates_external_vm(workspace):
    _, config = setup(workspace)
    path = Path(config.runtime_bindings_file)
    document = json.loads(path.read_text())
    document["NET-02"] = fixture_bindings()
    path.write_text(json.dumps(document))
    fake = FakeAzure()
    assert AzureStudyBackend(config, fake).preflight(["NET-01", "NET-02"]) == []
    assert sum(operation(a) == "account" for a, _ in fake.calls) == 1
    assert sum(operation(a) == "vm_show" for a, _ in fake.calls) == 1
    assert fake.group is None and not fake.vms


def test_public_preflight_preserves_net03_public_fixture_restriction(workspace):
    _, config = setup(workspace, bindings=public_web_bindings(), scenario_id="NET-03")
    fake = FakeAzure()
    assert AzureStudyBackend(config, fake).preflight(["NET-03"]) == []
    assert not any(operation(a) in {"public_ip_create", "nic_create", "vm_create"}
                   for a, _ in fake.calls)


def test_evaluate_retains_all_check_ids_when_preflight_blocks(workspace):
    result, _ = evaluate(workspace, FakeAzure(account=FileNotFoundError("az")),
                         checks=[check(id="alpha"), check("route", id="beta")])
    assert result["deployment_status"] == "blocked"
    assert result["runtime_status"] == "blocked"
    assert [(c["id"], c["status"]) for c in result["runtime_checks"]] == [
        ("alpha", "blocked"), ("beta", "blocked"),
    ]


def endpoint_bindings(name="benchmark-sql-pe"):
    return {
        "sources": {"web": EXTERNAL},
        "destinations": {"database": "benchmark-sql-{study_suffix}.database.windows.net"},
        "dns_private_addresses": {"database": {"private_endpoint": name}},
    }


@pytest.mark.parametrize("endpoint_name", ["benchmark-sql-pe", "benchmark-bus-pe"])
def test_dns_expected_ips_resolve_from_exact_deployed_private_endpoint_nic(workspace, endpoint_name):
    result, fake = evaluate(workspace, bindings=endpoint_bindings(endpoint_name),
                            checks=[check("dns_private")])
    assert result["runtime_status"] == "passed"
    endpoint_args = next(a for a, _ in fake.calls if operation(a) == "private_endpoint")
    assert arg(endpoint_args, "--name") == endpoint_name
    assert arg(endpoint_args, "--resource-group") == result["resource_group"]
    assert "10.1.3.4" not in Path(result["evidence_file"]).read_text()


def test_public_preflight_validates_endpoint_binding_without_looking_up_future_endpoint(workspace):
    _, config = setup(workspace, bindings=endpoint_bindings())
    fake = FakeAzure()
    assert AzureStudyBackend(config, fake).preflight(["NET-01"]) == []
    assert not any(operation(a) == "private_endpoint" for a, _ in fake.calls)
    assert fake.group is None


@pytest.mark.parametrize("spec", [
    {"private_endpoint": "../external"},
    {"private_endpoint": EXTERNAL},
    {"private_endpoint": "benchmark-sql-pe", "resource_group": "existing"},
    {"private_endpoint": None},
])
def test_preflight_rejects_unsafe_private_endpoint_bindings_locally(workspace, spec):
    bindings = endpoint_bindings()
    bindings["dns_private_addresses"]["database"] = spec
    _, config = setup(workspace, bindings=bindings)
    fake = FakeAzure()
    assert AzureStudyBackend(config, fake).preflight(["NET-01"])
    assert not fake.calls


@pytest.mark.parametrize("mode", [
    "wrong_id", "unapproved", "missing_nic", "foreign_nic", "foreign_subnet",
])
def test_private_endpoint_lookup_failures_cannot_pass_negative_dns_check(workspace, mode):
    def bad_endpoint(fake, args):
        root = fake.root
        data = {
            "id": root + "/providers/Microsoft.Network/privateEndpoints/benchmark-sql-pe",
            "subnet": {"id": root + "/providers/Microsoft.Network/virtualNetworks/benchmark-vnet/subnets/data"},
            "networkInterfaces": [{"id": root + "/providers/Microsoft.Network/networkInterfaces/endpoint-nic"}],
            "privateLinkServiceConnections": [{
                "privateLinkServiceConnectionState": {"status": "Approved"},
            }],
        }
        if mode == "wrong_id":
            data["id"] = EXTERNAL
        elif mode == "unapproved":
            data["privateLinkServiceConnections"][0]["privateLinkServiceConnectionState"]["status"] = "Pending"
        elif mode == "missing_nic":
            data["networkInterfaces"] = []
        elif mode == "foreign_nic":
            data["networkInterfaces"][0]["id"] = (
                f"/subscriptions/{OTHER_SUB}/resourceGroups/user/providers/"
                "Microsoft.Network/networkInterfaces/endpoint-nic"
            )
        else:
            data["subnet"]["id"] = (
                f"/subscriptions/{SUB}/resourceGroups/user/providers/"
                "Microsoft.Network/virtualNetworks/external/subnets/data"
            )
        return data
    result, _ = evaluate(workspace, FakeAzure(private_endpoint=bad_endpoint),
                         bindings=endpoint_bindings(), checks=[
                             check("dns_private", expected=False),
                         ])
    assert result["runtime_status"] == "blocked"


@pytest.mark.parametrize("mode", [
    "wrong_nic_id", "wrong_endpoint", "wrong_subnet", "public_ip", "no_ips", "invalid_ip",
])
def test_private_endpoint_nic_identity_and_ips_are_strict(workspace, mode):
    def bad_nic(fake, args):
        nic_id = arg(args, "--ids")
        if "endpoint-nic" not in nic_id:
            return {"id": nic_id, "ipConfigurations": [{"subnet": {
                "id": f"/subscriptions/{SUB}/resourceGroups/external-fixtures/"
                "providers/Microsoft.Network/virtualNetworks/external/subnets/probe",
            }}]}
        nic = json.loads(json.dumps(fake.nics[nic_id]))
        if mode == "wrong_nic_id":
            nic["id"] = EXTERNAL
        elif mode == "wrong_endpoint":
            nic["privateEndpoint"]["id"] = EXTERNAL
        elif mode == "wrong_subnet":
            nic["ipConfigurations"][0]["subnet"]["id"] = "external"
        elif mode == "public_ip":
            nic["ipConfigurations"][0]["publicIPAddress"] = {"id": "public"}
        elif mode == "no_ips":
            nic["ipConfigurations"] = []
        else:
            nic["ipConfigurations"][0]["privateIPAddress"] = "8.8.8.8"
        return nic
    result, _ = evaluate(workspace, FakeAzure(nic_show=bad_nic),
                         bindings=endpoint_bindings(), checks=[check("dns_private", expected=False)])
    assert result["runtime_status"] == "blocked"


def test_route_check_type_conflict_with_binding_is_blocked(workspace):
    result, _ = evaluate(workspace, checks=[
        check("route", expected_next_hop_type="Internet"),
    ])
    assert result["runtime_status"] == "blocked"
    assert result["runtime_checks"][0]["reason"] == "conflicting_route_expectation"


def test_route_checks_both_declared_type_and_bound_ip(workspace):
    result, _ = evaluate(workspace, FakeAzure(route={
        "nextHopType": "VirtualAppliance", "nextHopIpAddress": "10.1.0.99",
    }), checks=[check("route", expected_next_hop_type="VirtualAppliance")])
    assert result["runtime_status"] == "failed"


def service_bindings():
    return {"service_resources": {
        "sql": {"resource_type": "Microsoft.Sql/servers", "name": "benchmark-sql-{study_suffix}"},
        "bus": {"resource_type": "Microsoft.ServiceBus/namespaces", "name": "benchmark-bus-{study_suffix}"},
    }}


@pytest.mark.parametrize("role", ["sql", "bus"])
def test_disabled_public_access_is_actual_readonly_control_plane_observation_without_vm(workspace, role):
    result, fake = evaluate(workspace, bindings=service_bindings(), checks=[
        check("public_access_disabled", source="control-plane", destination=role),
    ])
    assert result["runtime_status"] == "passed"
    args = next(a for a, _ in fake.calls if operation(a) == "resource_show")
    kind = service_bindings()["service_resources"][role]["resource_type"]
    assert arg(args, "--ids") == (
        fake.root + f"/providers/{kind}/benchmark-{role}-{result['study_suffix']}"
    )
    assert not any(operation(a) in {
        "tcp", "vm_show", "nic_show", "run_command", "vm_create", "keygen",
    } for a, _ in fake.calls)
    providers = [arg(a, "--namespace") for a, _ in fake.calls if operation(a) == "provider"]
    assert "Microsoft.Compute" not in providers and "Microsoft.Network" not in providers
    assert "Microsoft.Sql" in providers and "Microsoft.ServiceBus" in providers


def test_public_access_enabled_is_failing_observation_not_tcp_test(workspace):
    def enabled(fake, args):
        return {"id": arg(args, "--ids"), "publicNetworkAccess": "Enabled"}
    result, fake = evaluate(workspace, FakeAzure(resource_show=enabled),
                            bindings=service_bindings(), checks=[
                                check("public_access_disabled", source="control-plane", destination="sql"),
                            ])
    assert result["runtime_status"] == "failed"
    assert not any(operation(a) == "tcp" for a, _ in fake.calls)


@pytest.mark.parametrize("response", [
    {}, None, {"id": EXTERNAL, "publicNetworkAccess": "Disabled"},
    subprocess.CompletedProcess([], 1, "SECRET", "SECRET"),
    subprocess.CompletedProcess([], 0, "not-json", ""),
    subprocess.TimeoutExpired(["az"], 180),
])
def test_missing_or_wrong_public_access_observation_is_blocked(workspace, response):
    result, _ = evaluate(workspace, FakeAzure(resource_show=response),
                         bindings=service_bindings(), checks=[
                             check("public_access_disabled", source="control-plane",
                                   destination="bus", expected=False),
                         ])
    assert result["runtime_status"] == "blocked"
    assert "SECRET" not in Path(result["evidence_file"]).read_text()


@pytest.mark.parametrize("value", [None, "Unknown", True, {}])
def test_public_access_property_must_have_known_explicit_value(workspace, value):
    def response(fake, args):
        return {"id": arg(args, "--ids"), "publicNetworkAccess": value}
    result, _ = evaluate(workspace, FakeAzure(resource_show=response),
                         bindings=service_bindings(), checks=[
                             check("public_access_disabled", source="control-plane",
                                   destination="sql", expected=False),
                         ])
    assert result["runtime_status"] == "blocked"


@pytest.mark.parametrize("source,destination", [("web", "sql"), ("control-plane", "storage")])
def test_control_plane_check_requires_exact_source_and_supported_destination(
    workspace, source, destination,
):
    result, fake = evaluate(workspace, bindings=service_bindings(), checks=[
        check("public_access_disabled", source=source, destination=destination),
    ])
    assert result["runtime_status"] == "blocked"
    assert not any(operation(a) == "resource_show" for a, _ in fake.calls)


def test_public_preflight_accepts_service_only_bindings_without_vm_or_future_resource_read(workspace):
    _, config = setup(workspace, bindings=service_bindings())
    fake = FakeAzure()
    assert AzureStudyBackend(config, fake).preflight(["NET-01"]) == []
    assert {operation(a) for a, _ in fake.calls} == {"account", "provider", "permissions"}


@pytest.mark.parametrize("spec", [
    {"resource_type": "Microsoft.Storage/storageAccounts", "name": "benchmark-storage"},
    {"resource_type": "Microsoft.ServiceBus/namespaces", "name": "benchmark-bus"},
    {"resource_type": "Microsoft.Sql/servers", "name": "../other"},
    {"resource_type": "Microsoft.Sql/servers", "name": "benchmark-sql", "resource_group": "user"},
])
def test_preflight_rejects_wrong_service_resource_types_or_scopes(workspace, spec):
    _, config = setup(workspace, bindings={"service_resources": {"sql": spec}})
    fake = FakeAzure()
    assert AzureStudyBackend(config, fake).preflight(["NET-01"])
    assert fake.calls == []


def firewall_route_bindings():
    return {
        "sources": {"web": EXTERNAL}, "source_ips": {"web": "10.1.1.4"},
        "destinations": {"internet": "8.8.8.8"},
        "route_destinations": {"internet": {
            "next_hop_type": "VirtualAppliance",
            "next_hop_ip": {"firewall": "benchmark-firewall"},
        }},
    }


def firewall_data(fake, args):
    return {
        "id": fake.root + "/providers/Microsoft.Network/azureFirewalls/benchmark-firewall",
        "ipConfigurations": [{
            "privateIPAddress": "10.1.0.4",
            "subnet": {"id": fake.root + "/providers/Microsoft.Network/virtualNetworks/"
                       "benchmark-hub/subnets/AzureFirewallSubnet"},
        }],
    }


def test_route_expected_ip_resolves_from_exact_trial_firewall(workspace):
    result, fake = evaluate(workspace, FakeAzure(firewall=firewall_data),
                            bindings=firewall_route_bindings(), checks=[
                                check("route", destination="internet",
                                      expected_next_hop_type="VirtualAppliance"),
                            ])
    assert result["runtime_status"] == "passed"
    args = next(a for a, _ in fake.calls if operation(a) == "firewall")
    assert arg(args, "--resource-group") == result["resource_group"]
    assert arg(args, "--name") == "benchmark-firewall"


def test_firewall_route_preflight_does_not_resolve_future_firewall(workspace):
    _, config = setup(workspace, bindings=firewall_route_bindings())
    fake = FakeAzure()
    assert AzureStudyBackend(config, fake).preflight(["NET-01"]) == []
    assert not any(operation(a) == "firewall" for a, _ in fake.calls)


@pytest.mark.parametrize("mode", ["wrong_id", "missing_ip", "public_ip", "wrong_subnet", "multiple_ips"])
def test_invalid_firewall_route_lookup_blocks_instead_of_guessing_ip(workspace, mode):
    def bad_firewall(fake, args):
        value = firewall_data(fake, args)
        if mode == "wrong_id":
            value["id"] = EXTERNAL
        elif mode == "missing_ip":
            value["ipConfigurations"][0].pop("privateIPAddress")
        elif mode == "public_ip":
            value["ipConfigurations"][0]["privateIPAddress"] = "8.8.8.8"
        elif mode == "wrong_subnet":
            value["ipConfigurations"][0]["subnet"]["id"] = "external"
        else:
            extra = json.loads(json.dumps(value["ipConfigurations"][0]))
            extra["privateIPAddress"] = "10.1.0.5"
            value["ipConfigurations"].append(extra)
        return value
    result, _ = evaluate(workspace, FakeAzure(firewall=bad_firewall),
                         bindings=firewall_route_bindings(), checks=[
                             check("route", destination="internet", expected=False,
                                   expected_next_hop_type="VirtualAppliance"),
                         ])
    assert result["runtime_status"] == "blocked"


@pytest.mark.parametrize("expected_ip", ["omitted", None, "", "0.0.0.0"])
@pytest.mark.parametrize("actual_ip", [None, "", "0.0.0.0"])
def test_discard_route_has_no_ip_and_accepts_explicit_zero_sentinel(workspace, expected_ip, actual_ip):
    bindings = firewall_route_bindings()
    route = {"next_hop_type": "None"}
    if expected_ip != "omitted":
        route["next_hop_ip"] = expected_ip
    bindings["route_destinations"]["internet"] = route
    result, _ = evaluate(workspace, FakeAzure(route={
        "nextHopType": "None", "nextHopIpAddress": actual_ip,
    }), bindings=bindings, checks=[
        check("route", destination="internet", expected_next_hop_type="None"),
    ])
    assert result["runtime_status"] == "passed"


def static_fixture_bindings(ip="10.1.1.4"):
    return {
        "sources": {"web": {
            "vnet": "benchmark-vnet", "subnet": "web", "vm_size": "Standard_B1s",
            "private_ip_address": ip,
        }},
        "destinations": {"app": {"source": "web", "listener_ports": [80]}},
    }


def test_static_fixture_ip_is_validated_and_bound_to_vm_through_exact_nic(workspace):
    result, fake = evaluate(workspace, bindings=static_fixture_bindings("10.1.1.42"))
    assert result["runtime_status"] == "passed"
    nic_args = next(a for a, _ in fake.calls if operation(a) == "nic_create")
    assert arg(nic_args, "--private-ip-address") == "10.1.1.42"
    vm_args = next(a for a, _ in fake.calls if operation(a) == "vm_create")
    nic_id = arg(vm_args, "--nics")
    assert fake.nics[nic_id]["ipConfigurations"][0]["privateIPAddress"] == "10.1.1.42"
    # --nics and VM --private-ip-address are mutually exclusive Azure CLI modes.
    assert "--private-ip-address" not in vm_args
    tcp_args = next(a for a, _ in fake.calls if operation(a) == "tcp")
    assert arg(tcp_args, "--dest-address") == "10.1.1.42"


@pytest.mark.parametrize("ip", [
    "10.1.1.0", "10.1.1.1", "10.1.1.2", "10.1.1.3", "10.1.1.255", "10.1.2.4",
])
def test_static_fixture_ip_outside_subnet_or_azure_reserved_is_blocked_before_nic(workspace, ip):
    result, fake = evaluate(workspace, bindings=static_fixture_bindings(ip))
    assert result["runtime_status"] == "blocked"
    assert not any(operation(a) in {"nic_create", "vm_create", "keygen"} for a, _ in fake.calls)
    assert result["runtime_checks"][0]["reason"] == "fixture_ip_outside_subnet_or_azure_reserved"


@pytest.mark.parametrize("ip", [None, True, 167837956, "10.1.1.4;echo bad", "fd00::4", "8.8.8.8"])
def test_preflight_rejects_invalid_static_fixture_ip_without_cloud_reads(workspace, ip):
    _, config = setup(workspace, bindings=static_fixture_bindings(ip))
    fake = FakeAzure()
    assert AzureStudyBackend(config, fake).preflight(["NET-01"])
    assert not fake.calls


def test_preflight_static_ip_does_not_lookup_not_yet_deployed_subnet(workspace):
    _, config = setup(workspace, bindings=static_fixture_bindings())
    fake = FakeAzure()
    assert AzureStudyBackend(config, fake).preflight(["NET-01"]) == []
    assert not any(operation(a) in {"subnet", "nic_create", "vm_create", "keygen"}
                   for a, _ in fake.calls)


def test_static_fixture_ip_must_be_honored_by_actual_created_nic(workspace):
    def incorrect_ip(fake, args):
        nic = fake.nics[arg(args, "--ids")]
        nic["ipConfigurations"][0]["privateIPAddress"] = "10.1.1.5"
        return nic
    result, fake = evaluate(workspace, FakeAzure(nic_show=incorrect_ip),
                            bindings=static_fixture_bindings())
    assert result["runtime_status"] == "blocked"
    assert result["runtime_checks"][0]["reason"] == "fixture_static_ip_not_honored"
    assert not fake.vms


def test_static_fixture_can_use_address_prefixes_array(workspace):
    def subnet(fake, args):
        return {
            "id": fake.root + "/providers/Microsoft.Network/virtualNetworks/benchmark-vnet/subnets/web",
            "addressPrefixes": ["10.1.1.0/24", "fd00::/64"],
        }
    result, _ = evaluate(workspace, FakeAzure(subnet=subnet), bindings=static_fixture_bindings())
    assert result["runtime_status"] == "passed"


def scoped_parameters_file(workspace, document=None):
    path = workspace / "scenario-parameters.json"
    if document is None:
        document = {"scenarios": {"NET-10": {"parameters": {
            "sqlAdministratorLogin": {"value": "studyadmin"},
            "sqlAdministratorPassword": {"value": "PRIVATE-SQL-PASSWORD"},
            "auditStorageEndpoint": {"value": "https://audit.example.org"},
            "auditStorageKey": {"value": "PRIVATE-AUDIT-KEY"},
            "studySuffix": {"value": "local"},
        }}}}
    path.write_text(json.dumps(document))
    return path


@pytest.mark.parametrize("scenario_id", ["NET-01", "NET-09", "NET-10"])
def test_scenario_parameters_select_only_exact_scenario_with_same_suffix_override(
    workspace, scenario_id,
):
    parameter_file = scoped_parameters_file(workspace)
    template, config = setup(
        workspace, scenario_id=scenario_id, parameters_file=str(parameter_file),
    )
    document = json.loads(template.read_text())
    document["parameters"] = {"studySuffix": {"type": "string", "defaultValue": "local"}}
    template.write_text(json.dumps(document))
    fake = FakeAzure()
    result = AzureStudyBackend(config, fake).evaluate(template, workspace, scenario_id, [])
    assert result["deployment_status"] == "passed"
    assert len(fake.parameter_documents) == 2
    validated, deployed = [document for _, document in fake.parameter_documents]
    assert validated == deployed
    if scenario_id == "NET-10":
        assert validated["parameters"]["sqlAdministratorPassword"]["value"] == "PRIVATE-SQL-PASSWORD"
        assert validated["parameters"]["auditStorageKey"]["value"] == "PRIVATE-AUDIT-KEY"
    else:
        assert validated == {"parameters": {}}
    for args, _ in fake.calls:
        assert "PRIVATE-SQL-PASSWORD" not in repr(args)
        assert "PRIVATE-AUDIT-KEY" not in repr(args)
        if operation(args) in {"validate", "deploy"}:
            assert f"studySuffix={result['study_suffix']}" in args
            assert not Path(arg(args, "--parameters")[1:]).exists()
    evidence = Path(result["evidence_file"]).read_text()
    assert "PRIVATE-SQL-PASSWORD" not in evidence and "PRIVATE-AUDIT-KEY" not in evidence
    assert parameter_file.exists()  # Never delete the operator's original file.
    assert not list(workspace.glob("study-cloud-*/parameters.json"))


def test_preflight_scenario_parameter_validation_never_materializes_selected_secrets(workspace):
    parameter_file = scoped_parameters_file(workspace)
    _, config = setup(workspace, parameters_file=str(parameter_file))
    fake = FakeAzure()
    before = sorted(str(p.relative_to(workspace)) for p in workspace.rglob("*"))
    assert AzureStudyBackend(config, fake).preflight(["NET-01"]) == []
    assert sorted(str(p.relative_to(workspace)) for p in workspace.rglob("*")) == before
    assert not fake.parameter_documents


@pytest.mark.parametrize("document", [
    {"scenarios": []}, {"scenarios": None},
    {"scenarios": {"NET-10": "SECRET"}},
    {"scenarios": {"NET-10": None}},
    {"scenarios": {"NET-10": []}},
    {"scenarios": {"": {"parameters": {}}}},
    {"scenarios": {"NET-10": {}}},
    {"scenarios": {"NET-10": {"parameters": []}}},
    {"scenarios": {"NET-10": {"parameters": {"password": "SECRET"}}}},
    {"scenarios": {"NET-10": {"parameters": {"password": {}}}}},
    {"scenarios": {"NET-10": {"parameters": {}, "extra": "SECRET"}}},
    {"scenarios": {}, "parameters": {}},
    {"scenarios": {}, "$schema": "anything"},
    {"parameters": {}, "NET-10": {"parameters": {}}},
    {"parameters": {}, "unknown": "SECRET"},
])
def test_preflight_rejects_malformed_or_mixed_parameter_schemas_without_cli(workspace, document):
    parameter_file = scoped_parameters_file(workspace, document)
    _, config = setup(workspace, parameters_file=str(parameter_file))
    fake = FakeAzure()
    reasons = AzureStudyBackend(config, fake).preflight(["NET-01"])
    assert reasons and "SECRET" not in repr(reasons)
    assert not fake.calls
    assert not list(workspace.glob("study-cloud-*"))


def test_all_scoped_entries_validated_even_when_selected_scenario_is_absent(workspace):
    parameter_file = scoped_parameters_file(workspace, {"scenarios": {"NET-10": False}})
    result, fake = evaluate(workspace, parameters_file=str(parameter_file), scenario_id="NET-01")
    assert result["deployment_status"] == "blocked"
    assert result["reason"] == "invalid_parameter_scenario_entry"
    assert not fake.calls


def test_unknown_selected_parameter_names_are_not_silently_filtered(workspace):
    parameter_file = scoped_parameters_file(workspace, {"scenarios": {
        "NET-01": {"parameters": {"notDeclaredByTemplate": {"value": "operator-value"}}},
    }})
    fake = FakeAzure(validate=subprocess.CompletedProcess([], 1, "", "unknown parameter"))
    result, _ = evaluate(workspace, fake, parameters_file=str(parameter_file))
    assert result["deployment_status"] == "blocked"
    assert fake.parameter_documents[0][1] == {
        "parameters": {"notDeclaredByTemplate": {"value": "operator-value"}},
    }
    assert not list(workspace.glob("study-cloud-*/parameters.json"))


@pytest.mark.parametrize("cleanup", [True, False])
def test_selected_secret_file_removed_on_validation_failure_regardless_of_rg_cleanup(workspace, cleanup):
    parameter_file = scoped_parameters_file(workspace)
    fake = FakeAzure(validate=subprocess.TimeoutExpired(["az", "SECRET"], 900))
    result, _ = evaluate(workspace, fake, parameters_file=str(parameter_file),
                         scenario_id="NET-10", cleanup=cleanup)
    assert result["deployment_status"] == "blocked"
    assert not list(workspace.glob("study-cloud-*/parameters.json"))
    assert "PRIVATE-SQL-PASSWORD" not in Path(result["evidence_file"]).read_text()


def test_flat_arm_parameters_are_forwarded_unchanged_and_not_deleted(workspace):
    document = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {"password": {"value": "PRIVATE-FLAT-PASSWORD"}},
    }
    parameter_file = scoped_parameters_file(workspace, document)
    result, fake = evaluate(workspace, parameters_file=str(parameter_file))
    assert result["deployment_status"] == "passed"
    assert [d for _, d in fake.parameter_documents] == [document, document]
    assert json.loads(parameter_file.read_text()) == document
    assert "PRIVATE-FLAT-PASSWORD" not in Path(result["evidence_file"]).read_text()


@pytest.mark.parametrize("cleanup", [True, False])
def test_private_fixture_keys_removed_even_when_rg_is_retained(workspace, cleanup):
    result, fake = evaluate(workspace, bindings=fixture_bindings(), cleanup=cleanup)
    assert result["runtime_status"] == "passed"
    assert not list(workspace.glob("study-cloud-*/probe_ed25519"))
    assert len(list(workspace.glob("study-cloud-*/probe_ed25519.pub"))) == 1
    assert sum(operation(a) == "keygen" for a, _ in fake.calls) == 1
    assert [entry["status"] for entry in result["operations"]
            if entry["operation"] == "fixture_private_key_cleanup"] == ["passed"]


def test_private_key_is_already_removed_before_vm_provisioning_and_stays_removed_on_failure(workspace):
    def failed_vm(fake, args):
        assert not list(workspace.glob("study-cloud-*/probe_ed25519"))
        return subprocess.CompletedProcess(args, 1, "", "provision failed")
    result, _ = evaluate(workspace, FakeAzure(vm_create=failed_vm),
                         bindings=static_fixture_bindings())
    assert result["runtime_status"] == "blocked"
    assert not list(workspace.glob("study-cloud-*/probe_ed25519"))
    assert len(list(workspace.glob("study-cloud-*/probe_ed25519.pub"))) == 1


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "missing_public"])
def test_partial_key_generation_private_file_is_always_removed(workspace, failure):
    def partial_keygen(fake, args):
        path = Path(arg(args, "-f"))
        path.write_text("PRIVATE-PARTIAL-KEY")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 30)
        if failure == "nonzero":
            return subprocess.CompletedProcess(args, 1, "", "PRIVATE-PARTIAL-KEY")
        return subprocess.CompletedProcess(args, 0, "", "")
    result, _ = evaluate(workspace, FakeAzure(keygen=partial_keygen),
                         bindings=static_fixture_bindings())
    assert result["runtime_status"] == "blocked"
    assert not list(workspace.glob("study-cloud-*/probe_ed25519"))
    assert "PRIVATE-PARTIAL-KEY" not in Path(result["evidence_file"]).read_text()
    assert any(entry == {"operation": "fixture_private_key_cleanup", "status": "passed"}
               for entry in result["operations"])


def test_existing_operator_private_key_at_exact_run_path_is_not_deleted_or_overwritten(
    workspace, monkeypatch,
):
    run_id = "a" * 32
    monkeypatch.setattr("network_simulation.study_cloud.uuid.uuid4",
                        lambda: SimpleNamespace(hex=run_id))
    directory = workspace / f"study-cloud-{run_id}"
    directory.mkdir()
    operator_private = directory / "probe_ed25519"
    operator_private.write_text("OPERATOR-PRIVATE-KEY")
    result, fake = evaluate(workspace, bindings=static_fixture_bindings())
    assert result["runtime_status"] == "blocked"
    assert operator_private.read_text() == "OPERATOR-PRIVATE-KEY"
    assert not any(operation(a) == "keygen" for a, _ in fake.calls)
    assert result["runtime_checks"][0]["reason"] == "fixture_key_path_already_exists"


def test_only_generated_exact_key_path_removed_not_other_operator_keys(workspace):
    operator_directory = workspace / "operator-keys"
    operator_directory.mkdir()
    operator_key = operator_directory / "probe_ed25519"
    operator_key.write_text("OPERATOR-PRIVATE-KEY")
    neighboring_key = operator_directory / "another-key"
    neighboring_key.write_text("ANOTHER-OPERATOR-KEY")
    result, _ = evaluate(workspace, bindings=static_fixture_bindings())
    assert result["runtime_status"] == "passed"
    assert not list(workspace.glob("study-cloud-*/probe_ed25519"))
    assert operator_key.read_text() == "OPERATOR-PRIVATE-KEY"
    assert neighboring_key.read_text() == "ANOTHER-OPERATOR-KEY"
