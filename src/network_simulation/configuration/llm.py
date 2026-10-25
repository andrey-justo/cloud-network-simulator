import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


AZURE_RESPONSES_MODELS = ["gpt-6.1-sol", "gpt-5.3-codex", "gpt-4o"]


@dataclass
class LLMConfig:
    provider: str = "azure_responses"
    model_name: str = "gpt-5.3-codex"
    available_models: list[str] = field(
        default_factory=lambda: AZURE_RESPONSES_MODELS.copy()
    )
    openai_api_key: str | None = None
    openai_organization: str | None = None
    anthropic_api_key: str | None = None
    azure_endpoint: str | None = None
    azure_api_key: str | None = None
    azure_auth_mode: str = "api_key"
    azure_tenant_id: str | None = None
    azure_subscription_id: str | None = None
    azure_deployment: str | None = None
    local_endpoint: str = "http://localhost:8080/v1"
    temperature: float | None = None
    max_tokens: int = 2000
    top_p: float | None = None

    @property
    def generation_settings(self) -> dict[str, float | int]:
        settings: dict[str, float | int] = {"max_output_tokens": self.max_tokens}
        if self.temperature is not None:
            settings["temperature"] = self.temperature
        if self.top_p is not None:
            settings["top_p"] = self.top_p
        return settings

    @classmethod
    def from_env(cls) -> "LLMConfig":
        dotenv_path = Path.cwd() / ".env"
        dotenv_configuration = dotenv_values(dotenv_path)
        load_dotenv(dotenv_path)
        provider = os.getenv("LLM_PROVIDER", "azure_responses")
        available_models = AZURE_RESPONSES_MODELS.copy()
        model_name = os.getenv("LLM_MODEL", "gpt-5.3-codex")
        if provider == "azure_responses" and model_name not in available_models:
            raise ValueError(
                f"Unsupported Azure Responses model '{model_name}'. "
                f"Choose one of: {', '.join(available_models)}"
            )

        dotenv_endpoint = next(
            (
                dotenv_configuration[name]
                for name in (
                    "AZURE_RESPONSES_ENDPOINT",
                    "AZURE_ENDPOINT",
                    "AZURE_OPENAI_ENDPOINT",
                    "DEFAULT_MODEL_ENDPOINT",
                )
                if dotenv_configuration.get(name)
            ),
            None,
        )
        dotenv_api_key = next(
            (
                dotenv_configuration[name]
                for name in (
                    "AZURE_RESPONSES_API_KEY",
                    "AZURE_API_KEY",
                    "AZURE_OPENAI_API_KEY",
                    "az_api_key",
                )
                if dotenv_configuration.get(name)
            ),
            None,
        )

        return cls(
            provider=provider,
            model_name=model_name,
            available_models=available_models,
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_organization=os.getenv("OPENAI_ORGANIZATION"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            azure_endpoint=dotenv_endpoint or os.getenv("AZURE_RESPONSES_ENDPOINT") or os.getenv(
                "AZURE_ENDPOINT",
                os.getenv("AZURE_OPENAI_ENDPOINT", os.getenv("DEFAULT_MODEL_ENDPOINT")),
            ),
            azure_api_key=(
                dotenv_api_key
                or os.getenv("AZURE_RESPONSES_API_KEY")
                or os.getenv("AZURE_API_KEY")
                or os.getenv("AZURE_OPENAI_API_KEY")
                or os.getenv("az_api_key")
            ),
            azure_deployment=os.getenv("AZURE_DEPLOYMENT"),
            azure_auth_mode=os.getenv("AZURE_AUTH_MODE", "api_key"),
            azure_tenant_id=os.getenv("AZURE_TENANT_ID"),
            azure_subscription_id=os.getenv("AZURE_SUBSCRIPTION_ID"),
        )

    def create_client(self):
        if self.provider != "azure_responses":
            raise ValueError(f"Unsupported LLM provider: {self.provider}")
        if self.model_name not in self.available_models:
            raise ValueError(f"Unsupported Azure Responses model: {self.model_name}")
        if not self.azure_endpoint:
            raise ValueError(
                "Set DEFAULT_MODEL_ENDPOINT or an Azure endpoint environment variable."
            )
        if self.azure_auth_mode not in ("api_key", "azure_cli"):
            raise ValueError("azure_auth_mode must be api_key or azure_cli.")
        if self.azure_auth_mode == "api_key" and not self.azure_api_key:
            raise ValueError(
                "Set az_api_key or an Azure API key environment variable before creating the client."
            )

        from network_simulation.azure_responses_client import AzureResponsesClient
        token_provider = None
        if self.azure_auth_mode == "azure_cli":
            try:
                from azure.identity import AzureCliCredential, get_bearer_token_provider
                from azure.core.exceptions import ClientAuthenticationError
            except ImportError as error:
                raise ValueError("Entra authentication requires the azure-auth extra: pip install '.[azure-auth]'.") from error
            provider = get_bearer_token_provider(
                AzureCliCredential(
                    tenant_id=self.azure_tenant_id or "",
                    subscription=self.azure_subscription_id,
                    process_timeout=30,
                ),
                "https://cognitiveservices.azure.com/.default",
            )

            def token_provider() -> str:
                try:
                    return provider()
                except ClientAuthenticationError as error:
                    raise ValueError("Microsoft Entra authentication failed; run az login for the configured tenant and verify Cognitive Services OpenAI User access.") from error

        return AzureResponsesClient(
            endpoint=self.azure_endpoint,
            model=self.model_name,
            api_key=self.azure_api_key if self.azure_auth_mode == "api_key" else None,
            token_provider=token_provider,
            max_output_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
        )