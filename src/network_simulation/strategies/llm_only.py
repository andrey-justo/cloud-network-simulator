from __future__ import annotations

from typing import Any, Mapping, Sequence

from .base import ExecutionStrategy


class LLMOnlyStrategy(ExecutionStrategy):
    """Strategy for prompt-only execution without external tools."""

    def execute(
        self,
        prompt: str,
        *,
        command: str | None = None,
        args: Sequence[str] | None = None,
        shell: str = "bash",
        method: str | None = None,
        params: Mapping[str, Any] | None = None,
        endpoint: str | None = None,
        llm_client: Any | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": "llm_only",
            "prompt": prompt,
            "status": "ok",
            "provider": "local-placeholder",
            "metadata": {},
        }

        if llm_client is not None:
            payload["provider"] = getattr(llm_client, "provider", "custom")
            model = getattr(llm_client, "model", None)
            if model:
                payload["metadata"]["model"] = model
            try:
                provider_response = llm_client(prompt)
                if isinstance(provider_response, Mapping):
                    payload.update(provider_response)
                    payload["status"] = payload.get("status", "ok")
                elif isinstance(provider_response, str):
                    payload["response"] = provider_response
            except Exception as exc:  # pragma: no cover - defensive path
                payload["status"] = "error"
                payload["error"] = str(exc)

        return payload


__all__ = ["LLMOnlyStrategy"]
