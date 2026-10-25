import pytest

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
    assert config.validation.opa_policies_dir == "policies/azure"
    assert config.validation.opa_policies_dir == "policies/azure"