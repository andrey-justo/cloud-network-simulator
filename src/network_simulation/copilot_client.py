from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Coroutine
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from copilot import CopilotClient

T = TypeVar("T")


class CopilotAuthenticationError(ValueError):
    pass


class CopilotGenerationClient:
    """Synchronous, stateless generation through the pinned Copilot SDK."""

    provider = "copilot"

    def __init__(self, *, model: str, max_output_tokens: int = 2000) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("A Copilot model identifier is required.")
        if type(max_output_tokens) is not int or max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive integer.")
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.last_usage: dict[str, int] | None = None
        self.last_response_metadata: dict[str, Any] = {}

    def __call__(self, prompt: str) -> str:
        self.last_usage = None
        self.last_response_metadata = {}
        return self._run(self._request(prompt))

    @staticmethod
    def _run(coroutine: Coroutine[Any, Any, T]) -> T:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)
        coroutine.close()
        raise RuntimeError(
            "Run the synchronous Copilot adapter outside an active asyncio loop."
        )

    @classmethod
    def list_models(cls, *, allow_login: bool = False) -> list[str]:
        try:
            return cls._run(cls._discover())
        except CopilotAuthenticationError:
            if not allow_login:
                raise
        cls._browser_login()
        return cls._run(cls._discover())

    @staticmethod
    def _browser_login() -> None:
        executable = os.environ.get("COPILOT_CLI_PATH")
        if not executable:
            local_appdata = os.environ.get("LOCALAPPDATA")
            installed_cli = (
                Path(local_appdata) / "Microsoft" / "WinGet" / "Links" / "copilot.exe"
                if os.name == "nt" and local_appdata
                else None
            )
            executable = (
                str(installed_cli)
                if installed_cli is not None and installed_cli.is_file()
                else shutil.which("copilot")
            )
        if not executable:
            raise ValueError(
                "Browser authentication requires the standalone Copilot CLI. "
                "Install it, then retry with --login."
            )
        print(
            "Opening Copilot browser sign-in; cached credentials were unavailable.",
            file=sys.stderr,
        )
        try:
            result = subprocess.run(
                [executable, "login", "--web-flow"],
                stdout=sys.stderr,
                check=False,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(
                "Copilot browser sign-in could not complete. Run copilot login "
                "in a terminal, then retry. No generation request was sent."
            ) from error
        if result.returncode != 0:
            raise ValueError(
                f"Copilot browser sign-in exited with code {result.returncode}. "
                "Complete CLI login before retrying; no generation request was sent."
            )

    @staticmethod
    def _sdk() -> type[CopilotClient]:
        try:
            from copilot import CopilotClient
        except ImportError as error:
            raise ValueError(
                "Copilot requires the copilot extra: pip install -e '.[copilot]'."
            ) from error
        return CopilotClient

    @staticmethod
    async def _models(client: CopilotClient) -> list[str]:
        status = await client.get_auth_status()
        if not status.isAuthenticated:
            raise CopilotAuthenticationError(
                "Copilot is not authenticated. Sign in with Copilot CLI or retry "
                "with --login to open browser sign-in."
            )
        models = await client.list_models()
        return sorted(
            model.id
            for model in models
            if model.policy is None or model.policy.state == "enabled"
        )

    @classmethod
    async def _discover(cls) -> list[str]:
        sdk = cls._sdk()
        from copilot.session import JsonRpcError, ProcessExitedError

        try:
            with TemporaryDirectory(prefix="iac-copilot-discovery-") as directory:
                async with sdk(
                    working_directory=directory,
                    use_logged_in_user=True,
                    log_level="error",
                ) as client:
                    return await cls._models(client)
        except (JsonRpcError, ProcessExitedError, OSError, TimeoutError) as error:
            raise RuntimeError(
                "Copilot discovery failed; verify the SDK runtime, CLI login and network access."
            ) from error

    async def _request(self, prompt: str) -> str:
        sdk = self._sdk()
        from copilot.generated.rpc import PermissionDecisionReject
        from copilot.session import (
            JsonRpcError,
            ModelCapabilitiesOverride,
            ModelLimitsOverride,
            ProcessExitedError,
        )
        from copilot.session_events import (
            AssistantMessageData,
            AssistantUsageData,
            SessionErrorData,
            SessionIdleData,
            ToolExecutionStartData,
        )

        usage_events: list[AssistantUsageData] = []
        failure: str | None = None
        response: str | None = None
        done = asyncio.Event()

        def deny_permission(request, invocation):
            nonlocal failure
            failure = "Copilot requested a permission during tool-free generation."
            return PermissionDecisionReject()

        def on_event(event):
            nonlocal response, failure
            if event.agent_id:
                return
            data = event.data
            if isinstance(data, AssistantUsageData):
                usage_events.append(data)
            elif isinstance(data, AssistantMessageData):
                response = data.content
                if data.tool_requests:
                    failure = "Copilot requested tools during tool-free generation."
                    done.set()
            elif isinstance(data, SessionErrorData):
                failure = "Copilot generation failed; check model access, quota and service availability."
                done.set()
            elif isinstance(data, ToolExecutionStartData):
                failure = "Copilot attempted a tool call during tool-free generation."
                done.set()
            elif isinstance(data, SessionIdleData):
                if data.aborted:
                    failure = "Copilot generation was aborted."
                done.set()

        try:
            with TemporaryDirectory(prefix="iac-copilot-generation-") as directory:
                async with sdk(
                    working_directory=directory,
                    use_logged_in_user=True,
                    log_level="error",
                ) as client:
                    if self.model not in await self._models(client):
                        raise ValueError(
                            f"Copilot model '{self.model}' is unavailable or disabled; "
                            "run python -m network_simulation.copilot_client --list-models."
                        )
                    session = await client.create_session(
                        model=self.model,
                        available_tools=[],
                        tools=[],
                        mcp_servers={},
                        custom_agents=[],
                        additional_directories=[],
                        enable_config_discovery=False,
                        skip_custom_instructions=True,
                        interactive_user=False,
                        enable_experimental_mode=False,
                        enable_session_telemetry=False,
                        enable_file_change_tracking=False,
                        enable_skills=False,
                        enable_file_hooks=False,
                        enable_host_git_operations=False,
                        enable_session_store=False,
                        enable_github_cache_store=False,
                        skip_embedding_retrieval=True,
                        enable_on_demand_instruction_discovery=False,
                        plugin_directories=[],
                        skill_directories=[],
                        agent_directories=[],
                        hook_directories=[],
                        instruction_directories=[],
                        included_builtin_skills=[],
                        system_message={
                            "mode": "customize",
                            "sections": {"environment_context": {"action": "remove"}},
                        },
                        memory={"enabled": False},
                        infinite_sessions={"enabled": False},
                        model_capabilities=ModelCapabilitiesOverride(
                            limits=ModelLimitsOverride(
                                max_output_tokens=self.max_output_tokens
                            )
                        ),
                        on_permission_request=deny_permission,
                        on_event=on_event,
                    )
                    try:
                        async with session:
                            self.last_response_metadata = {
                                "provider": self.provider,
                                "sdk_version": version("github-copilot-sdk"),
                                "session_id": session.session_id,
                                "requested_model": self.model,
                            }
                            await session.send(prompt)
                            await asyncio.wait_for(done.wait(), timeout=180)
                    finally:
                        await client.delete_session(session.session_id)
        except (JsonRpcError, ProcessExitedError, OSError, TimeoutError) as error:
            raise RuntimeError(
                "Copilot request failed; verify runtime, CLI login, quota and network access."
            ) from error
        finally:
            self.last_response_metadata.update(
                usage_event_count=len(usage_events),
                reported_models=sorted({event.model for event in usage_events}),
                finish_reasons=[
                    event.finish_reason
                    for event in usage_events
                    if event.finish_reason is not None
                ],
            )
            if usage_events and all(
                type(getattr(event, key)) is int and getattr(event, key) >= 0
                for event in usage_events
                for key in ("input_tokens", "output_tokens")
            ):
                self.last_usage = {
                    key: sum(getattr(event, key) for event in usage_events)
                    for key in ("input_tokens", "output_tokens")
                }
        if failure:
            raise RuntimeError(failure)
        if any(
            event.finish_reason
            in ("length", "max_tokens", "max_output_tokens", "content_filter")
            or event.content_filter_triggered
            for event in usage_events
        ):
            raise ValueError("Copilot returned an incomplete or filtered generation.")
        if not isinstance(response, str) or not response.strip():
            raise ValueError("Copilot returned no text output.")
        return response


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover available Copilot models without sending a generation prompt."
    )
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument(
        "--login",
        action="store_true",
        help="Open browser sign-in only if cached credentials are unavailable.",
    )
    args = parser.parse_args()
    if not args.list_models and not args.login:
        parser.error("Specify --list-models or --login.")
    try:
        models = CopilotGenerationClient.list_models(
            allow_login=args.login or sys.stdin.isatty()
        )
    except (ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {"status": "blocked", "error": str(error), "generation_requests": 0}
            )
        )
        return 2
    print(json.dumps({"models": models, "generation_requests": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
