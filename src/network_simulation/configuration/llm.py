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
        if not self.azure_api_key:
            raise ValueError(
                "Set az_api_key or an Azure API key environment variable before creating the client."
            )

        from network_simulation.azure_responses_client import AzureResponsesClient

        return AzureResponsesClient(
            endpoint=self.azure_endpoint,
            model=self.model_name,
            api_key=self.azure_api_key,
            max_output_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
        )