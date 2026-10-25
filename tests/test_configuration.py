import pytest
from dataclasses import asdict

from network_simulation.configuration import (
    AZURE_RESPONSES_MODELS,
    LLMConfig,
    POCConfig,
    PromptConfig,
)


def test_prompts_load_from_markdown_templates() -> None:
    prompts = PromptConfig()

    assert "Bicep" in prompts.system_prompt_b1
    assert "Checkov" in prompts.system_prompt_t1
    assert "{validation_failures}" in prompts.system_prompt_iterative


def test_llm_config_selects_each_allowed_model(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "azure_responses")

    for model in AZURE_RESPONSES_MODELS:
        monkeypatch.setenv("LLM_MODEL", model)
        assert LLMConfig.from_env().model_name == model


def test_llm_config_rejects_unknown_model(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "azure_responses")
    monkeypatch.setenv("LLM_MODEL", "unknown-model")

    with pytest.raises(ValueError, match="Unsupported Azure Responses model"):
        LLMConfig.from_env()


def test_llm_config_loads_workspace_dotenv_aliases(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "DEFAULT_MODEL_ENDPOINT=https://azure.example.test/openai/responses?api-version=test\n"
        "az_api_key=test-key\n",
        encoding="utf-8",
    )
    for name in (
        "AZURE_RESPONSES_ENDPOINT",
        "AZURE_ENDPOINT",
        "AZURE_OPENAI_ENDPOINT",
        "DEFAULT_MODEL_ENDPOINT",
        "AZURE_RESPONSES_API_KEY",
        "AZURE_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "az_api_key",
    ):
        monkeypatch.delenv(name, raising=False)

    config = LLMConfig.from_env()

    assert config.azure_endpoint == (
        "https://azure.example.test/openai/responses?api-version=test"
    )
    assert config.azure_api_key == "test-key"


def test_workspace_dotenv_credentials_override_inherited_azure_credentials(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "DEFAULT_MODEL_ENDPOINT=https://azure.example.test/openai/responses?api-version=test\n"
        "az_api_key=project-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AZURE_RESPONSES_API_KEY", "inherited-key")

    config = LLMConfig.from_env()

    assert config.azure_api_key == "project-key"


def test_llm_config_does_not_default_to_an_unconfigured_endpoint(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AZURE_RESPONSES_API_KEY", "test-key")
    monkeypatch.delenv("DEFAULT_MODEL_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_RESPONSES_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)

    config = LLMConfig.from_env()

    assert config.azure_endpoint is None
    with pytest.raises(ValueError, match="Set DEFAULT_MODEL_ENDPOINT"):
        config.create_client()


def test_poc_config_uses_loaded_prompts() -> None:
    config = POCConfig()

    assert config.prompts.system_prompt_b1
    assert config.experiment.run_b0 is False
    assert config.validation.opa_policies_dir == "policies/azure"
    assert config.validation.opa_policies_dir == "policies/azure"


def test_configuration_round_trip_preserves_settings_without_secrets(tmp_path):
    config = POCConfig()
    config.poc_name = "review experiment"
    config.experiment.experiment_phase = "main"
    config.experiment.main_scenarios = ["NET-10"]
    config.experiment.t1_max_iterations = 2
    config.experiment.run_b1 = False
    config.experiment.output_directory = "custom-results"
    config.validation.run_opa_policies = False
    config.validation.custom_checks_dir = "checks"
    config.llm.model_name = "gpt-4o"
    config.llm.temperature = 0.1
    config.llm.top_p = 0.7
    config.llm.max_tokens = 1700
    config.llm.azure_api_key = "do-not-save"
    config.prompts.system_prompt_b1 = "Custom B1"
    path = tmp_path / "config.yml"
    config.save_yaml(str(path))
    loaded = POCConfig.load_yaml(str(path))
    assert "do-not-save" not in path.read_text(encoding="utf-8")
    config.llm.azure_api_key = None
    assert asdict(loaded) == asdict(config)


def test_configuration_loads_legacy_keys(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(
        "experiment:\n  phase: main\n  scenarios: [NET-10]\n  max_iterations_t1: 2\n"
        "llm:\n  model: gpt-4o\nvalidation:\n  checkov: false\n  opa: false\n  bicep_syntax: true\n",
        encoding="utf-8",
    )
    config = POCConfig.load_yaml(str(path))
    assert config.experiment.main_scenarios == ["NET-10"]
    assert config.experiment.t1_max_iterations == 2
    assert config.llm.model_name == "gpt-4o"
    assert config.validation.run_checkov is False
    assert config.validation.run_opa_policies is False


@pytest.mark.parametrize("text", [
    "[]", "validation: false", "validation:\n  checkov: 'false'",
    "experiment:\n  max_iterations_t1: 0", "llm:\n  unknown: true",
    "unknown: {}", "prompts: []",
])
def test_configuration_rejects_invalid_input(tmp_path, text):
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        POCConfig.load_yaml(str(path))


def test_configuration_rejects_unsupported_model_sampling():
    config = LLMConfig(
        azure_endpoint="https://example.test/responses",
        azure_api_key="test",
        temperature=0.1,
    )
    with pytest.raises(ValueError, match="Sampling settings"):
        config.create_client()