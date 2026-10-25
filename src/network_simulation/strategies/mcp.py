from __future__ import annotations

from typing import Any, Mapping, Sequence

from .base import ExecutionStrategy


class MCPStrategy(ExecutionStrategy):
    """Strategy for MCP-style tool invocation."""

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
        payload = {
            "mode": "mcp",
            "prompt": prompt,
            "endpoint": endpoint or "stdio://default",
            "method": method or "tools/list",
            "params": dict(params or {}),
            "status": "ok",
            "response": {
                "implemented": True,
                "transport": "mocked",
            },
        }

        if not payload["method"]:
            payload["status"] = "error"
            payload["error"] = "method is required"

        return payload


__all__ = ["MCPStrategy"]
