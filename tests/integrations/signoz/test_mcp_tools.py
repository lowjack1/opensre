"""SigNoz MCP tools: read-only by allow-list, connected from the integration's settings."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import mcp_types as types
import pytest

import integrations.mcp_client as mcp_client
from integrations.catalog import load_env_integrations
from integrations.signoz.tools import _signoz_mcp_available, call_signoz_tool, list_signoz_tools

MCP_URL = "http://signoz-mcp:8000/mcp"


@dataclass
class _Server:
    """The SigNoz MCP server: read tools, a write tool, and tools it marks as writes."""

    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    sessions: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    async def list_tools(self) -> object:
        def tool(name: str, read_only: bool | None = None) -> types.Tool:
            hint = None if read_only is None else types.ToolAnnotations(read_only_hint=read_only)
            return types.Tool(name=name, input_schema={"type": "object"}, annotations=hint)

        tools = [
            tool("signoz_get_alert", read_only=True),
            tool("signoz_execute_builder_query"),
            tool("signoz_delete_alert", read_only=False),
            tool("signoz_list_alerts", read_only=False),  # on the list, but the server says no
            tool("signoz_new_unknown_tool", read_only=True),  # not on the list
        ]
        return type("Listing", (), {"tools": tools})()

    async def call_tool(self, name: str, arguments: dict[str, object]) -> types.CallToolResult:
        self.calls.append((name, arguments))
        return types.CallToolResult(content=[types.TextContent(text=f"{name} ran")])


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> _Server:
    fake = _Server()

    @asynccontextmanager
    async def open_session(config: object, **options: object) -> AsyncIterator[_Server]:
        fake.sessions.append((str(options["session_url"]), dict(config.request_headers)))  # type: ignore[attr-defined]
        yield fake

    monkeypatch.setattr(mcp_client, "open_mcp_session", open_session)
    return fake


def test_only_read_only_tools_are_listed(server: _Server) -> None:
    result = list_signoz_tools(mcp_url=MCP_URL, api_key="k3y")
    assert result["available"] is True
    assert sorted(t["name"] for t in result["tools"]) == [
        "signoz_execute_builder_query",
        "signoz_get_alert",
    ]
    assert server.sessions == [(MCP_URL, {"SIGNOZ-API-KEY": "k3y"})]


def test_a_read_only_tool_is_called(server: _Server) -> None:
    arguments = {"id": "rule-1"}
    result = call_signoz_tool(tool_name="signoz_get_alert", arguments=arguments, mcp_url=MCP_URL)
    assert (result["available"], result["text"]) == (True, "signoz_get_alert ran")
    assert server.calls == [("signoz_get_alert", arguments)]


@pytest.mark.parametrize("name", ["signoz_delete_alert", "signoz_update_alert", "anything"])
def test_any_other_tool_is_refused_without_contacting_the_server(
    server: _Server, name: str
) -> None:
    result = call_signoz_tool(tool_name=name, arguments={"id": "rule-1"}, mcp_url=MCP_URL)
    assert result["available"] is False
    assert "not one of the read-only SigNoz MCP tools" in str(result["error"])
    assert server.calls == [] and server.sessions == []


def test_without_an_mcp_url_the_tools_say_so(server: _Server) -> None:
    assert list_signoz_tools()["available"] is False
    assert "SIGNOZ_MCP_URL" in str(call_signoz_tool(tool_name="signoz_get_alert")["error"])
    assert server.sessions == []


def test_the_tools_are_read_only_and_never_take_the_server_from_the_model() -> None:
    from tools.registry import get_registered_tool

    for name in ("list_signoz_tools", "call_signoz_tool"):
        registered = get_registered_tool(name)
        assert registered is not None
        assert registered.side_effect_level == "read_only"
        assert not {"mcp_url", "api_key"} & set(registered.public_input_schema["properties"])


def test_signoz_mcp_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNOZ_URL", "https://signoz.example.com")
    monkeypatch.setenv("SIGNOZ_API_KEY", "k3y")
    monkeypatch.setenv("SIGNOZ_MCP_URL", MCP_URL)
    [signoz] = [r for r in load_env_integrations() if r["service"] == "signoz"]
    assert signoz["credentials"]["mcp_url"] == MCP_URL
    assert _signoz_mcp_available({"signoz": {**signoz["credentials"], "connection_verified": True}})

    monkeypatch.delenv("SIGNOZ_MCP_URL")
    [signoz] = [r for r in load_env_integrations() if r["service"] == "signoz"]
    assert not _signoz_mcp_available(
        {"signoz": {**signoz["credentials"], "connection_verified": True}}
    )
