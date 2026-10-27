import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from network_simulation.configuration import LLMConfig, POCConfig
from network_simulation.copilot_client import CopilotGenerationClient, main
from network_simulation.study import ControlledStudyRunner

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sdk(monkeypatch):
    copilot = pytest.importorskip("copilot")
    from copilot.session_events import (
        AssistantMessageData,
        AssistantUsageData,
        SessionIdleData,
    )

    state = SimpleNamespace(
        authenticated=True,
        models=["test-model"],
        sessions=[],
        clients=[],
        deleted=[],
        prompts=[],
        events=[
            AssistantUsageData(model="test-model", input_tokens=12, output_tokens=8),
            AssistantMessageData(content="// generated", message_id="test"),
            SessionIdleData(),
        ],
        transport_error=None,
        cleanup_error=None,
        discovery_error=None,
    )

    class Session:
        def __init__(self, options):
            self.options = options
            self.session_id = f"test-session-{len(state.sessions)}"
            state.sessions.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def send(self, prompt):
            state.prompts.append(prompt)
            if state.transport_error:
                raise state.transport_error
            for data in state.events:
                self.options["on_event"](SimpleNamespace(data=data, agent_id=None))

    class Client:
        def __init__(self, **options):
            state.clients.append(options)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            state.stopped = True

        async def get_auth_status(self):
            if state.discovery_error:
                raise state.discovery_error
            return SimpleNamespace(isAuthenticated=state.authenticated)

        async def list_models(self):
            return [SimpleNamespace(id=model, policy=None) for model in state.models]

        async def create_session(self, **options):
            return Session(options)

        async def delete_session(self, session_id):
            state.deleted.append(session_id)
            if state.cleanup_error:
                raise state.cleanup_error

    monkeypatch.setattr(copilot, "CopilotClient", Client)
    return state


def test_copilot_generation_is_isolated_tool_free_and_records_usage(sdk):
    import inspect

    from copilot.client import CopilotClient as SDKClient

    client = CopilotGenerationClient(model="test-model", max_output_tokens=1234)
    assert client("first") == "// generated"
    assert client("second") == "// generated"
    assert client.last_usage == {"input_tokens": 12, "output_tokens": 8}
    assert client.last_response_metadata["reported_models"] == ["test-model"]
    assert client.last_response_metadata["usage_event_count"] == 1
    assert sdk.prompts == ["first", "second"]
    assert len({session.session_id for session in sdk.sessions}) == 2
    assert sdk.deleted == [session.session_id for session in sdk.sessions]
    assert sdk.stopped
    for options in sdk.clients:
        assert not Path(options["working_directory"]).exists()
        assert Path(options["working_directory"]) != ROOT
        assert options["use_logged_in_user"] is True
    for session in sdk.sessions:
        options = session.options
        inspect.signature(SDKClient.create_session).bind(object(), **options)
        assert options["model"] == "test-model"
        assert options["model_capabilities"].limits.max_output_tokens == 1234
        assert options["available_tools"] == options["tools"] == []
        assert options["mcp_servers"] == {}
        assert options["custom_agents"] == []
        assert options["memory"] == {"enabled": False}
        assert options["infinite_sessions"] == {"enabled": False}
        assert options["enable_config_discovery"] is False
        assert options["skip_custom_instructions"] is True
        assert options["enable_skills"] is False
        assert options["enable_file_hooks"] is False
        assert options["enable_session_store"] is False
        assert options["skip_embedding_retrieval"] is True
        assert options["system_message"]["sections"]["environment_context"] == {
            "action": "remove"
        }
        assert session.closed


def test_discovery_never_creates_a_session_or_sends_prompts(sdk):
    assert CopilotGenerationClient.list_models() == ["test-model"]
    assert sdk.sessions == sdk.prompts == []


def test_cached_authentication_never_opens_a_browser(sdk, monkeypatch):
    monkeypatch.setattr(
        CopilotGenerationClient,
        "_browser_login",
        lambda: pytest.fail("Cached authentication must be reused"),
    )
    assert CopilotGenerationClient.list_models(allow_login=True) == ["test-model"]
    assert sdk.prompts == []


def test_browser_login_is_opt_in_and_rechecks_the_credential_cache(sdk, monkeypatch):
    sdk.authenticated = False
    logins = []

    def login():
        logins.append(True)
        sdk.authenticated = True

    monkeypatch.setattr(CopilotGenerationClient, "_browser_login", login)
    with pytest.raises(ValueError, match="--login"):
        CopilotGenerationClient.list_models()
    assert logins == []
    assert CopilotGenerationClient.list_models(allow_login=True) == ["test-model"]
    assert logins == [True]
    assert sdk.prompts == []


def test_unsuccessful_cache_refresh_does_not_loop(sdk, monkeypatch):
    sdk.authenticated = False
    logins = []
    monkeypatch.setattr(
        CopilotGenerationClient, "_browser_login", lambda: logins.append(True)
    )
    with pytest.raises(ValueError, match="authenticated"):
        CopilotGenerationClient.list_models(allow_login=True)
    assert len(logins) == 1
    assert len(sdk.clients) == 2
    assert sdk.prompts == []


def test_transport_failure_does_not_trigger_browser_login(sdk, monkeypatch):
    from copilot.session import JsonRpcError

    sdk.discovery_error = JsonRpcError(-1, "sensitive detail")
    monkeypatch.setattr(
        CopilotGenerationClient,
        "_browser_login",
        lambda: pytest.fail("Only missing credentials may trigger browser login"),
    )
    with pytest.raises(RuntimeError, match="discovery failed"):
        CopilotGenerationClient.list_models(allow_login=True)


def test_browser_login_uses_the_official_cli_without_handling_token_values(monkeypatch):
    import sys

    calls = []
    monkeypatch.setenv("COPILOT_CLI_PATH", "test-copilot.exe")
    monkeypatch.setattr(
        "network_simulation.copilot_client.subprocess.run",
        lambda *args, **kwargs: (
            calls.append((args, kwargs)) or SimpleNamespace(returncode=0)
        ),
    )
    CopilotGenerationClient._browser_login()
    assert calls == [
        (
            (["test-copilot.exe", "login", "--web-flow"],),
            {"stdout": sys.stderr, "check": False, "timeout": 300},
        )
    ]


@pytest.mark.parametrize("failure", ["exit", "missing", "timeout"])
def test_browser_login_failure_is_explicit_and_sanitized(monkeypatch, failure):
    import subprocess

    monkeypatch.setenv("COPILOT_CLI_PATH", "test-copilot.exe")

    def login(*args, **kwargs):
        if failure == "missing":
            raise FileNotFoundError("sensitive detail")
        if failure == "timeout":
            raise subprocess.TimeoutExpired("sensitive detail", 300)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr("network_simulation.copilot_client.subprocess.run", login)
    with pytest.raises(ValueError, match="sign-in") as error:
        CopilotGenerationClient._browser_login()
    assert "sensitive detail" not in str(error.value)


def test_interactive_discovery_prompts_only_when_needed(sdk, monkeypatch, capsys):
    sdk.authenticated = False
    monkeypatch.setattr("sys.argv", ["copilot_client", "--list-models"])
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(
        CopilotGenerationClient,
        "_browser_login",
        lambda: setattr(sdk, "authenticated", True),
    )
    assert main() == 0
    assert '"generation_requests": 0' in capsys.readouterr().out
    assert sdk.prompts == []


def test_login_only_command_works_without_generating(sdk, monkeypatch, capsys):
    sdk.authenticated = False
    monkeypatch.setattr("sys.argv", ["copilot_client", "--login"])
    monkeypatch.setattr(
        CopilotGenerationClient,
        "_browser_login",
        lambda: setattr(sdk, "authenticated", True),
    )
    assert main() == 0
    assert '"test-model"' in capsys.readouterr().out
    assert sdk.prompts == []


@pytest.mark.parametrize("arguments", [["--login"], ["--dry-run", "--login"]])
def test_study_planning_cannot_request_browser_authentication(sdk, arguments):
    from network_simulation.main import main as study_main

    with pytest.raises(SystemExit) as error:
        study_main(
            ["--config", str(ROOT / "configs" / "smoke-static.yaml"), *arguments]
        )
    assert error.value.code == 2
    assert sdk.clients == []


@pytest.mark.parametrize(
    "interactive,login", [(False, False), (True, False), (False, True)]
)
def test_study_execution_forwards_browser_permission_only_when_allowed(
    sdk, monkeypatch, capsys, interactive, login
):
    from network_simulation.main import main as study_main

    options = []

    def run(self, scenarios, **kwargs):
        options.append(kwargs)
        return {"status": "completed", "output_directory": "test"}

    monkeypatch.setattr(ControlledStudyRunner, "run", run)
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: interactive))
    arguments = ["--config", str(ROOT / "configs" / "smoke-static.yaml"), "--execute"]
    if login:
        arguments.append("--login")
    assert study_main(arguments) == 0
    capsys.readouterr()
    assert options == [{"allow_browser_auth": interactive or login}]
    assert sdk.clients == []


@pytest.mark.parametrize(
    "authenticated,models", [(False, ["test-model"]), (True, ["other"])]
)
def test_authentication_and_unavailable_models_block_before_generation(
    sdk, authenticated, models
):
    sdk.authenticated = authenticated
    sdk.models = models
    with pytest.raises(ValueError, match="authenticated|unavailable"):
        CopilotGenerationClient(model="test-model")("test")
    assert sdk.prompts == sdk.sessions == []


def test_missing_sdk_has_an_actionable_error(monkeypatch):
    import builtins

    importing = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "copilot":
            raise ImportError("missing optional package")
        return importing(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(ValueError, match="copilot extra"):
        CopilotGenerationClient.list_models()


def test_failures_clear_stale_usage_and_missing_usage_remains_unknown(sdk):
    client = CopilotGenerationClient(model="test-model")
    client("first")
    sdk.authenticated = False
    with pytest.raises(ValueError, match="authenticated"):
        client("second")
    assert client.last_usage is None
    sdk.authenticated = True
    sdk.events = sdk.events[1:]
    assert client("third") == "// generated"
    assert client.last_usage is None
    assert client.last_response_metadata["usage_event_count"] == 0


def test_multiple_usage_events_are_summed_without_inventing_dollar_cost(sdk):
    sdk.events.insert(0, sdk.events[0])
    client = CopilotGenerationClient(model="test-model")
    client("test")
    assert client.last_usage == {"input_tokens": 24, "output_tokens": 16}
    assert client.last_response_metadata["usage_event_count"] == 2
    assert "cost_usd" not in client.last_response_metadata


@pytest.mark.parametrize(
    "failure", ["length", "session-error", "tool", "aborted", "empty", "permission"]
)
def test_incomplete_aborted_and_agentic_responses_fail_closed(sdk, failure):
    from copilot.session_events import (
        SessionErrorData,
        SessionIdleData,
        ToolExecutionStartData,
    )

    if failure == "length":
        sdk.events[0].finish_reason = "length"
    elif failure == "session-error":
        sdk.events.insert(
            0, SessionErrorData(error_type="test", message="sensitive detail")
        )
    elif failure == "tool":
        sdk.events.insert(
            0, ToolExecutionStartData(tool_call_id="test", tool_name="shell")
        )
    elif failure == "aborted":
        sdk.events[-1] = SessionIdleData(aborted=True)
    elif failure == "permission":
        original = sdk.events

        class PermissionEvents:
            def __iter__(self):
                result = sdk.sessions[-1].options["on_permission_request"](None, {})
                assert result.kind == "reject"
                return iter(original)

        sdk.events = PermissionEvents()
    else:
        sdk.events[1].content = ""
    with pytest.raises((RuntimeError, ValueError)) as error:
        CopilotGenerationClient(model="test-model")("test")
    assert "sensitive detail" not in str(error.value)
    assert sdk.deleted == ["test-session-0"]
    assert sdk.stopped


def test_transport_errors_are_sanitized_and_cleanup_is_attempted(sdk):
    from copilot.session import JsonRpcError

    sdk.transport_error = JsonRpcError(-1, "sensitive transport detail")
    with pytest.raises(RuntimeError, match="Copilot request failed") as error:
        CopilotGenerationClient(model="test-model")("test")
    assert "sensitive transport detail" not in str(error.value)
    assert sdk.deleted == ["test-session-0"]


def test_cleanup_failure_is_not_reported_as_success(sdk):
    sdk.cleanup_error = RuntimeError("session cleanup failed")
    with pytest.raises(RuntimeError, match="cleanup failed"):
        CopilotGenerationClient(model="test-model")("test")


def test_synchronous_adapter_rejects_nested_event_loops(sdk):
    async def invoke():
        with pytest.raises(RuntimeError, match="active asyncio loop"):
            CopilotGenerationClient(model="test-model")("test")

    asyncio.run(invoke())
    assert not sdk.clients


def test_configuration_and_planning_need_neither_azure_credentials_nor_sdk_start(
    sdk, tmp_path
):
    config = POCConfig()
    config.llm = LLMConfig(provider="copilot", model_name="test-model")
    config.study.models = ["test-model"]
    path = tmp_path / "config.yaml"
    config.save_yaml(str(path))
    loaded = POCConfig.load_yaml(str(path))
    client = loaded.llm.create_client()
    assert isinstance(client, CopilotGenerationClient)
    plan = ControlledStudyRunner(workspace_dir=ROOT, config=loaded).plan(["NET-01"])
    assert plan["provider"] == "copilot"
    assert plan["authentication_mode"] == "github_copilot"
    assert plan["maximum_physical_model_calls"] is None
    assert plan["maximum_generation_requests"] > 0
    assert sdk.clients == []


@pytest.mark.parametrize("setting", ["temperature", "top_p"])
def test_unsupported_sampling_is_not_silently_ignored(setting):
    config = LLMConfig(provider="copilot")
    setattr(config, setting, 0.5)
    with pytest.raises(ValueError, match="does not expose"):
        config.create_client()


def test_all_requested_models_are_checked_before_any_trial(sdk, tmp_path):
    config = POCConfig()
    config.llm.provider = "copilot"
    config.study.models = ["test-model", "unavailable"]
    config.experiment.output_directory = str(tmp_path / "results")
    runner = ControlledStudyRunner(workspace_dir=ROOT, config=config)
    result = runner.run(["NET-01"])
    assert result["status"] == "blocked_preflight"
    assert any("unavailable" in error for error in result["preflight_errors"])
    assert sdk.prompts == sdk.sessions == []


def test_discovery_command_reports_auth_block_without_prompt(sdk, monkeypatch, capsys):
    sdk.authenticated = False
    monkeypatch.setattr("sys.argv", ["copilot_client", "--list-models"])
    assert main() == 2
    assert '"generation_requests": 0' in capsys.readouterr().out
    assert sdk.prompts == []


def test_copilot_study_accounts_for_shared_generation_without_azure_token_prices(
    sdk, tmp_path
):
    import json

    config = POCConfig()
    config.llm = LLMConfig(provider="copilot", model_name="test-model")
    config.study.models = ["test-model"]
    config.study.repetitions = 1
    config.study.input_usd_per_million = 10
    config.study.output_usd_per_million = 20
    config.validation.run_checkov = False
    config.validation.run_opa_policies = False
    config.experiment.output_directory = str(tmp_path / "results")

    def compile_candidate(source, output):
        output.write_text('{"resources": []}', encoding="utf-8")
        return {"status": "passed"}

    runner = ControlledStudyRunner(
        workspace_dir=ROOT,
        config=config,
        bicep_compiler=SimpleNamespace(
            executable="test-only-compiler", validate=compile_candidate
        ),
    )
    result = runner.run(["NET-01"])
    assert result["status"] == "completed"
    assert result["generation_requests"] == 1
    assert result["physical_model_calls"] is None
    assert len(sdk.prompts) == 1
    calls = json.loads(
        (Path(result["output_directory"]) / "calls.json").read_text(encoding="utf-8")
    )
    assert calls[0]["usage"] == {"input_tokens": 12, "output_tokens": 8}
    assert calls[0]["cost_usd"] is None
    assert all(
        not condition["accepted"]
        for condition in result["trials"][0]["conditions"].values()
    )
