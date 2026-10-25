from pathlib import Path

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
        shell="bash",
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
