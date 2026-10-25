from __future__ import annotations

from typing import Any

import requests


class AzureResponsesClient:
    """Callable client for an Azure OpenAI Responses endpoint."""

    provider = "azure_responses"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        api_key: str,
        timeout: float = 120.0,
        max_output_tokens: int = 2000,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> None:
        if not endpoint:
            raise ValueError("Azure Responses endpoint is required.")
        if not model:
            raise ValueError("Azure Responses model is required.")
        if not api_key:
            raise ValueError("Azure Responses API key is required.")
        if type(max_output_tokens) is not int or max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive integer.")
        if temperature is not None and not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2.")
        if top_p is not None and not 0 < top_p <= 1:
            raise ValueError("top_p must be greater than 0 and at most 1.")
        if (temperature is not None or top_p is not None) and not (
            model == "gpt-4o" or model.startswith("gpt-4o-")
        ):
            raise ValueError(
                "Sampling settings are supported only for gpt-4o in this client; "
                "leave temperature and top_p unset for reasoning models."
            )
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.last_usage: dict[str, int] | None = None
        self.last_response_metadata: dict[str, Any] = {}
        self.generation_settings: dict[str, float | int] = {"max_output_tokens": max_output_tokens}
        if temperature is not None:
            self.generation_settings["temperature"] = temperature
        if top_p is not None:
            self.generation_settings["top_p"] = top_p

    def __call__(self, prompt: str) -> str:
        self.last_usage = None
        self.last_response_metadata = {}
        response = requests.post(
            self.endpoint,
            headers={
                "api-key": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                **self.generation_settings,
                "model": self.model,
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": prompt}],
                    }
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Azure Responses API returned a non-object JSON payload.")
        self.last_response_metadata = {
            key: payload[key] for key in ("id", "model", "created_at", "status")
            if isinstance(payload.get(key), (str, int, float))
        }
        usage = payload.get("usage")
        if isinstance(usage, dict) and all(
            type(usage.get(key)) is int and usage[key] >= 0
            for key in ("input_tokens", "output_tokens")
        ):
            self.last_usage = {key: usage[key] for key in ("input_tokens", "output_tokens")}
        return self._extract_text(payload)

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        if payload.get("status") in ("incomplete", "failed", "cancelled"):
            raise ValueError(
                f"Azure Responses generation {payload['status']}: "
                f"{payload.get('incomplete_details') or payload.get('error')}"
            )
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        chunks: list[str] = []
        for item in payload.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text)
        if chunks:
            return "\n".join(chunks)
        raise ValueError("Azure Responses API returned no text output.")