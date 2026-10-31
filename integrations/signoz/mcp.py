"""Read-only access to a SigNoz MCP server (github.com/SigNoz/signoz-mcp-server).

The Query API tools cover logs, metrics and traces with fixed filters. The MCP server adds
alert rules and their history, dashboards, field discovery, and builder queries with any
filter, group-by and aggregation. It can also create, update and delete alerts, dashboards
and notification channels, so only the tools in ``READ_ONLY_TOOLS`` are listed or called,
and a tool the server marks as not read-only is refused even if it is on the list.
"""

from __future__ import annotations

from typing import cast

from mcp_types import Tool
from pydantic import Field, field_validator

from config.strict_config import StrictConfigModel
from integrations.mcp_client import (
    McpSessionOptions,
    call_mcp_tool,
    list_mcp_tools,
    root_cause_message,
)
from integrations.mcp_transport import McpTransportMode

READ_ONLY_TOOLS = frozenset(
    {
        "signoz_get_alert",
        "signoz_get_alert_history",
        "signoz_list_alert_rules",
        "signoz_list_alerts",
        "signoz_list_dashboards",
        "signoz_get_dashboard",
        "signoz_list_services",
        "signoz_get_service_top_operations",
        "signoz_get_field_keys",
        "signoz_get_field_values",
        "signoz_search_logs",
        "signoz_aggregate_logs",
        "signoz_search_traces",
        "signoz_aggregate_traces",
        "signoz_get_trace_details",
        "signoz_query_metrics",
        "signoz_list_metrics",
        "signoz_execute_builder_query",
    }
)


class SigNozMCPConfig(StrictConfigModel):
    """A SigNoz MCP server over streamable HTTP; satisfies ``McpClientConfig``."""

    url: str
    api_key: str = ""
    timeout_seconds: float = Field(default=60.0, gt=0)

    @field_validator("url", mode="before")
    @classmethod
    def _normalize_url(cls, value: object) -> str:
        return str(value or "").strip().rstrip("/")

    @property
    def mode(self) -> McpTransportMode:
        return McpTransportMode.STREAMABLE_HTTP

    @property
    def command(self) -> str:
        return ""

    @property
    def args(self) -> tuple[str, ...]:
        return ()

    @property
    def request_headers(self) -> dict[str, str]:
        # The server can also hold the key itself; sending it lets one server serve many keys.
        return {"SIGNOZ-API-KEY": self.api_key} if self.api_key else {}


class SigNozMCPRefused(ValueError):
    """A call to a SigNoz MCP tool that isn't read-only."""


def _session_options(config: SigNozMCPConfig) -> McpSessionOptions:
    return {
        "session_url": config.url,
        "stdio_env": {},
        "integration_name": "SigNoz",
        "config_env_name": "SIGNOZ_MCP",
        "streamable_url_hint": "http://localhost:8000/mcp",
    }


def is_read_only(tool: Tool) -> bool:
    """On the allow-list, and not marked otherwise by the server."""
    if tool.annotations is not None and tool.annotations.read_only_hint is False:
        return False
    return tool.name in READ_ONLY_TOOLS


def list_signoz_mcp_tools(config: SigNozMCPConfig) -> list[dict[str, object]]:
    """The server's read-only tools, as name, description and input schema."""
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.input_schema,
        }
        for tool in list_mcp_tools(config, **_session_options(config))
        if is_read_only(tool)
    ]


def call_signoz_mcp_tool(
    config: SigNozMCPConfig, tool_name: str, arguments: dict[str, object] | None = None
) -> dict[str, object]:
    """Calls a read-only tool; anything else is refused before the server is contacted."""
    if tool_name not in READ_ONLY_TOOLS:
        raise SigNozMCPRefused(
            f"{tool_name!r} is not one of the read-only SigNoz MCP tools; "
            "use list_signoz_tools to see them."
        )
    return cast(
        dict[str, object],
        call_mcp_tool(config, tool_name, arguments, timeout_call=True, **_session_options(config)),
    )


def describe_signoz_mcp_error(err: BaseException) -> str:
    return root_cause_message(err, timeout_message="SigNoz MCP tool call timed out")
