from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

from network_simulation.engine import ExecutionEngine, ExecutionMode


def test_engine_llm_only_mode_returns_prompt_summary() -> None:
    engine = ExecutionEngine(mode=ExecutionMode.LLM_ONLY)

    result = engine.run("Generate a secure Azure VNet layout")

    assert result["mode"] == ExecutionMode.LLM_ONLY
    assert "Generate a secure Azure VNet layout" in result["prompt"]
    assert result["status"] == "ok"


def test_engine_can_execute_cli_tool() -> None:
    engine = ExecutionEngine(mode=ExecutionMode.CLI_TOOL)
    tool_result = engine.call_cli_tool(
        command="echo",
        args=["hello-from-cli"],
        shell="powershell" if os.name == "nt" else "bash",
    )

    assert tool_result["returncode"] == 0
    assert "hello-from-cli" in tool_result["stdout"]


def test_engine_can_call_mcp_endpoint() -> None:
    engine = ExecutionEngine(mode=ExecutionMode.MCP)

    result = engine.call_mcp(
        method="tools/list",
        params={"name": "network-check"},
        endpoint="stdio://dummy-mcp-server",
    )

    assert result["mode"] == ExecutionMode.MCP
    assert result["method"] == "tools/list"
    assert result["status"] == "ok"


def test_engine_calls_azure_responses_client(monkeypatch) -> None:
    from network_simulation.azure_responses_client import AzureResponsesClient

    request = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, str]:
            return {"output_text": "resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {}"}

    def fake_post(endpoint, *, headers, json, timeout):
        request.update(
            endpoint=endpoint,
            headers=headers,
            payload=json,
            timeout=timeout,
        )
        return FakeResponse()

    monkeypatch.setattr(
        "network_simulation.azure_responses_client.requests.post", fake_post
    )
    client = AzureResponsesClient(
        endpoint="https://example.test/openai/responses?api-version=test",
        model="gpt-5.3-codex",
        api_key="test-key",
    )
    engine = ExecutionEngine(llm_client=client)

    result = engine.run("Generate a VNet")

    assert result["response"].startswith("resource vnet")
    assert result["provider"] == "azure_responses"
    assert result["metadata"]["model"] == "gpt-5.3-codex"
    assert request["payload"]["model"] == "gpt-5.3-codex"
    assert request["payload"]["input"][0]["content"][0]["text"] == "Generate a VNet"
    assert request["payload"]["max_output_tokens"] == 2000


def test_cli_honors_working_directory_environment_and_quoting(tmp_path):
    script = tmp_path / "script with spaces.py"
    script.write_text(
        "import os, sys, json\n"
        "print(json.dumps({'cwd': os.getcwd(), 'env': os.getenv('REVIEW_VAR'), 'args': sys.argv[1:]}))",
        encoding="utf-8",
    )
    arguments = ["O'Brien", 'double"quote', "", "$literal; & text", "space value"]
    engine = ExecutionEngine(mode=ExecutionMode.CLI_TOOL)
    result = engine.call_cli_tool(
        command=sys.executable,
        args=[str(script), *arguments],
        shell="powershell" if os.name == "nt" else "bash",
        cwd=str(tmp_path),
        env={"REVIEW_VAR": "forwarded"},
    )
    assert result["returncode"] == 0, result["stderr"]
    actual = json.loads(result["stdout"])
    assert Path(actual["cwd"]) == tmp_path
    assert actual["env"] == "forwarded"
    assert actual["args"] == arguments


def test_cli_nonzero_exit_does_not_repeat_command_in_another_shell(monkeypatch):
    calls = []
    monkeypatch.setattr("network_simulation.strategies.cli_tool.shutil.which", lambda name, **kwargs: name)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 7, "", "command failed")

    monkeypatch.setattr("network_simulation.strategies.cli_tool.subprocess.run", fake_run)
    result = ExecutionEngine(mode="cli_tool").run(
        "test", command="tool", shell="bash", params={"cwd": "test-directory", "env": {"CUSTOM": "1"}}
    )
    assert result["returncode"] == 7
    assert len(calls) == 1
    assert calls[0][1]["cwd"] == "test-directory"
    assert calls[0][1]["env"]["CUSTOM"] == "1"


def test_cli_resolves_native_command_using_overridden_path(monkeypatch):
    lookups = []

    def which(name, **kwargs):
        lookups.append((name, kwargs.get("path")))
        return "custom-tool.exe" if name == "custom-tool" else name

    monkeypatch.setattr("network_simulation.strategies.cli_tool.shutil.which", which)
    monkeypatch.setattr(
        "network_simulation.strategies.cli_tool.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )
    result = ExecutionEngine(mode="cli_tool").call_cli_tool(
        command="custom-tool", args=["value"], env={"PATH": "custom-search-path"},
    )
    assert result["returncode"] == 0
    assert ("custom-tool", "custom-search-path") in lookups


@pytest.mark.skipif(os.name != "nt", reason="PowerShell built-in regression")
def test_powershell_builtin_preserves_apostrophes():
    result = ExecutionEngine(mode="cli_tool").call_cli_tool(
        command="Write-Output", args=["O'Brien"], shell="powershell"
    )
    assert result["returncode"] == 0
    assert result["stdout"].strip() == "O'Brien"


def test_azure_client_sends_configured_generation_settings(monkeypatch):
    from network_simulation.configuration import LLMConfig
    from types import SimpleNamespace

    payloads = []
    monkeypatch.setattr(
        "network_simulation.azure_responses_client.requests.post",
        lambda *args, **kwargs: payloads.append(kwargs["json"]) or SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"output_text": "template"}
        ),
    )
    client = LLMConfig(
        model_name="gpt-4o", azure_endpoint="https://example.test",
        azure_api_key="test", temperature=0.2, top_p=0.8, max_tokens=1234,
    ).create_client()
    client("prompt")
    assert payloads[0]["temperature"] == 0.2
    assert payloads[0]["top_p"] == 0.8
    assert payloads[0]["max_output_tokens"] == 1234


def test_azure_client_rejects_truncated_generation():
    from network_simulation.azure_responses_client import AzureResponsesClient

    with pytest.raises(ValueError, match="incomplete"):
        AzureResponsesClient._extract_text({
            "status": "incomplete", "output_text": "partial template",
            "incomplete_details": {"reason": "max_output_tokens"},
        })
