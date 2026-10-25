from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence


class ExecutionStrategy(ABC):
    """Base strategy contract for execution modes."""

    @abstractmethod
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
        raise NotImplementedError


__all__ = ["ExecutionStrategy"]
