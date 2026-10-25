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
    ) -> None:
        if not endpoint:
            raise ValueError("Azure Responses endpoint is required.")
        if not model:
            raise ValueError("Azure Responses model is required.")
        if not api_key:
            raise ValueError("Azure Responses API key is required.")
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def __call__(self, prompt: str) -> str:
        response = requests.post(
            self.endpoint,
            headers={
                "api-key": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
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
        return self._extract_text(response.json())

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
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