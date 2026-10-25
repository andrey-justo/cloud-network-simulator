import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from network_simulation.azure_responses_client import AzureResponsesClient
from network_simulation.configuration import LLMConfig, POCConfig
from network_simulation.live_experiment import LiveExperimentRunner
from network_simulation.study import ControlledStudyRunner
from network_simulation.study_acceptance import evaluate_structure
from network_simulation.validation.bicep_compiler import BicepCompiler
from network_simulation.validation.checkov_validator import is_checkov_available
from network_simulation.validation.conftest_validator import ConftestValidator

ROOT = Path(__file__).resolve().parents[1]


def response():
    return SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"output_text": "// test"}
    )


def test_entra_uses_bearer_tokens_for_each_request_without_api_key(monkeypatch):
    calls = []
    tokens = iter(("first-test-token", "second-test-token"))
    monkeypatch.setattr(
        "network_simulation.azure_responses_client.requests.post",
        lambda *args, **kwargs: calls.append(kwargs["headers"]) or response(),
    )
    client = AzureResponsesClient(
        endpoint="https://example.test",
        model="gpt-5.3-codex",
        token_provider=lambda: next(tokens),
    )
    client("one")
    client("two")
    assert [call["Authorization"] for call in calls] == [
        "Bearer first-test-token",
        "Bearer second-test-token",
    ]
    assert all("api-key" not in call for call in calls)


@pytest.mark.parametrize("token", ["", " ", None, "bad token", "bad\ntoken"])
def test_invalid_tokens_never_reach_the_model_endpoint(monkeypatch, token):
    monkeypatch.setattr(
        "network_simulation.azure_responses_client.requests.post",
        lambda *args, **kwargs: pytest.fail("No request may be made"),
    )
    client = AzureResponsesClient(
        endpoint="https://example.test",
        model="gpt-5.3-codex",
        token_provider=lambda: token,
    )
    with pytest.raises(ValueError, match="invalid token"):
        client("test")


def test_ambiguous_authentication_and_non_https_entra_are_rejected():
    with pytest.raises(ValueError, match="exactly one"):
        AzureResponsesClient(
            endpoint="https://example.test",
            model="test",
            api_key="test",
            token_provider=lambda: "test",
        )
    with pytest.raises(ValueError, match="HTTPS"):
        AzureResponsesClient(
            endpoint="http://example.test", model="test", token_provider=lambda: "test"
        )


def test_cli_credential_wiring_is_lazy_and_ignores_existing_api_keys(monkeypatch):
    identity = pytest.importorskip("azure.identity")
    credentials = []
    scopes = []
    monkeypatch.setattr(
        identity,
        "AzureCliCredential",
        lambda **kwargs: credentials.append(kwargs) or object(),
    )
    monkeypatch.setattr(
        identity,
        "get_bearer_token_provider",
        lambda credential, scope: scopes.append(scope) or (lambda: "mock-entra-token"),
    )
    config = LLMConfig(
        azure_endpoint="https://example.test",
        azure_auth_mode="azure_cli",
        azure_api_key="must-not-be-used",
        azure_tenant_id="test-tenant",
        azure_subscription_id="test-subscription",
    )
    client = config.create_client()
    assert client.api_key is None
    assert credentials == [
        {
            "tenant_id": "test-tenant",
            "subscription": "test-subscription",
            "process_timeout": 30,
        }
    ]
    assert scopes == ["https://cognitiveservices.azure.com/.default"]
    assert client.token_provider() == "mock-entra-token"


def test_authentication_failure_does_not_fall_back_or_leak_sdk_details(monkeypatch):
    identity = pytest.importorskip("azure.identity")
    from azure.core.exceptions import ClientAuthenticationError

    def failed():
        raise ClientAuthenticationError("sensitive SDK detail")

    monkeypatch.setattr(identity, "AzureCliCredential", lambda **kwargs: object())
    monkeypatch.setattr(identity, "get_bearer_token_provider", lambda *args: failed)
    monkeypatch.setattr(
        "network_simulation.azure_responses_client.requests.post",
        lambda *args, **kwargs: pytest.fail("No fallback request"),
    )
    client = LLMConfig(
        azure_endpoint="https://example.test",
        azure_auth_mode="azure_cli",
        azure_api_key="unused",
    ).create_client()
    with pytest.raises(ValueError, match="Entra authentication failed") as error:
        client("prompt")
    assert "sensitive SDK detail" not in str(error.value)


def test_missing_optional_sdk_has_an_actionable_error(monkeypatch):
    import builtins

    original = builtins.__import__

    def importing(name, *args, **kwargs):
        if name == "azure.identity":
            raise ImportError("test missing optional dependency")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    with pytest.raises(ValueError, match="azure-auth"):
        LLMConfig(
            azure_endpoint="https://example.test", azure_auth_mode="azure_cli"
        ).create_client()


def test_entra_configuration_round_trip_and_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AZURE_AUTH_MODE", "azure_cli")
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "subscription")
    config = POCConfig()
    config.llm = LLMConfig.from_env()
    path = tmp_path / "config.yaml"
    config.save_yaml(str(path))
    loaded = POCConfig.load_yaml(str(path))
    assert loaded.llm.azure_auth_mode == "azure_cli"
    assert loaded.llm.azure_tenant_id == "tenant"
    assert loaded.llm.azure_subscription_id == "subscription"


@pytest.mark.parametrize(
    ("filename", "trials", "calls", "scenarios"),
    [
        ("pilot-static.yaml", 100, 900, 10),
        ("smoke-static.yaml", 2, 6, 1),
    ],
)
def test_prepared_batches_have_the_exact_requested_shape(
    filename, trials, calls, scenarios
):
    config = POCConfig.load_yaml(str(ROOT / "configs" / filename))
    keys = config.experiment.pilot_scenarios
    plan = ControlledStudyRunner(workspace_dir=ROOT, config=config).plan(keys)
    assert plan["models"] == ["gpt-5.3-codex", "gpt-6.1-sol"]
    assert len(plan["schedule"]) == trials
    assert len(plan["scenarios"]) == scenarios
    assert plan["maximum_physical_model_calls"] == calls
    assert plan["maximum_cloud_deployments"] == 0
    assert plan["authentication_mode"] == "azure_cli"
    assert plan["paid_execution"] is False


def test_real_local_validator_smoke_when_tools_are_installed(tmp_path):
    config = POCConfig()
    runner = LiveExperimentRunner(workspace_dir=ROOT, config=config)
    if (
        not runner.bicep_compiler.executable
        or not runner.conftest_validator.executable
        or not is_checkov_available()
    ):
        pytest.skip(
            "Optional local Bicep, Checkov and Conftest integration tools are not installed."
        )
    source = ROOT / "tests" / "fixtures" / "net01-valid.bicep"
    compiled = tmp_path / "template.json"
    assert runner.bicep_compiler.validate(source, compiled)["status"] == "passed"
    # Keep generated validation output in the temporary directory, not beside the fixture.
    candidate = tmp_path / "template.bicep"
    candidate.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    report = runner.validate_candidate(candidate, "NET-01")
    assert all(item["status"] == "passed" for item in report.values()), report
    assert evaluate_structure(compiled, "NET-01")["status"] == "passed"
    document = json.loads(compiled.read_text(encoding="utf-8"))
    vnet = document["resources"][0]
    subnet = vnet["properties"]["subnets"].pop()
    document["resources"].append(
        {
            "type": "Microsoft.Network/virtualNetworks/subnets",
            "name": f"{vnet['name']}/{subnet['name']}",
            "properties": subnet["properties"],
        }
    )
    compiled.write_text(json.dumps(document), encoding="utf-8")
    assert (
        runner.conftest_validator.validate(compiled, ROOT / "policies" / "azure")[
            "status"
        ]
        == "passed"
    )
    assert evaluate_structure(compiled, "NET-01")["status"] == "passed"
    document["resources"][-1]["name"] = "unrelated/web"
    compiled.write_text(json.dumps(document), encoding="utf-8")
    assert (
        runner.conftest_validator.validate(compiled, ROOT / "policies" / "azure")[
            "status"
        ]
        == "failed"
    )


def test_managed_bicep_and_user_local_conftest_are_discovered(monkeypatch, tmp_path):
    import os

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("BICEP_CLI", raising=False)
    monkeypatch.delenv("CONFTEST_CLI", raising=False)
    monkeypatch.setattr(
        "network_simulation.validation.bicep_compiler.shutil.which", lambda _: None
    )
    monkeypatch.setattr(
        BicepCompiler, "_find_winget_install", staticmethod(lambda: None)
    )
    bicep = tmp_path / ".azure" / "bin" / ("bicep.exe" if os.name == "nt" else "bicep")
    conftest = (
        tmp_path
        / ".local"
        / "bin"
        / ("conftest.exe" if os.name == "nt" else "conftest")
    )
    for path in (bicep, conftest):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
    assert BicepCompiler().executable == str(bicep)
    assert ConftestValidator().executable == str(conftest)
    assert ConftestValidator(executable="").executable is None
