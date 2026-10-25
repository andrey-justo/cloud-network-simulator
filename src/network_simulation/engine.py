from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Sequence

from network_simulation.strategies.cli_tool import CLIToolStrategy
from network_simulation.strategies.llm_only import LLMOnlyStrategy
from network_simulation.strategies.mcp import MCPStrategy


class ExecutionMode(str, Enum):
    """Supported execution modes for the network simulation engine."""

    LLM_ONLY = "llm_only"
    CLI_TOOL = "cli_tool"
    MCP = "mcp"


class ExecutionEngine:
    """Execution engine facade backed by strategy implementations."""

    def __init__(
        self,
        mode: ExecutionMode | str = ExecutionMode.LLM_ONLY,
        llm_client: Any | None = None,
    ) -> None:
        self.mode = ExecutionMode(mode)
        self.llm_client = llm_client
        self._strategies = {
            ExecutionMode.LLM_ONLY: LLMOnlyStrategy(),
            ExecutionMode.CLI_TOOL: CLIToolStrategy(),
            ExecutionMode.MCP: MCPStrategy(),
        }

    def _strategy(self):
        return self._strategies[self.mode]

    def call_llm(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Execute a simple LLM-style call via the LLM strategy."""
        return self._strategy().execute(
            prompt,
            llm_client=self.llm_client,
            **kwargs,
        )

    def call_cli_tool(
        self,
        command: str,
        args: Sequence[str] | None = None,
        shell: str = "bash",
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Invoke a local CLI tool via the CLI strategy."""
        return self._strategy().execute(
            prompt="",
            command=command,
            args=args,
            shell=shell,
            params={"cwd": cwd, "env": dict(env or {})},
        )

    def call_mcp(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        endpoint: str = "stdio://default",
    ) -> dict[str, Any]:
        """Call an MCP endpoint via the MCP strategy."""
        return self._strategy().execute(
            prompt="",
            method=method,
            params=params,
            endpoint=endpoint,
        )

    def run(
        self,
        prompt: str,
        *,
        command: str | None = None,
        args: Sequence[str] | None = None,
        shell: str = "bash",
        method: str | None = None,
        params: Mapping[str, Any] | None = None,
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        """Execute the engine in the configured mode."""
        if self.mode == ExecutionMode.LLM_ONLY:
            return self.call_llm(prompt)

        if self.mode == ExecutionMode.CLI_TOOL:
            if not command:
                raise ValueError("A CLI command is required when mode is CLI_TOOL.")
            return self.call_cli_tool(command=command, args=args, shell=shell)

        if self.mode == ExecutionMode.MCP:
            return self.call_mcp(
                method=method or "tools/list",
                params=params,
                endpoint=endpoint or "stdio://default",
            )

        raise ValueError(f"Unsupported execution mode: {self.mode!r}")


__all__ = ["ExecutionEngine", "ExecutionMode"]
