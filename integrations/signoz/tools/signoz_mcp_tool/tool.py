"""Read-only SigNoz MCP tools: a discovery tool plus a named-call tool.

The server's URL and key come from the integration, never from the model, so a tool call
can't be pointed at another server. Only read-only tools are listed or called (see
``integrations.signoz.mcp``).
"""

from __future__ import annotations

from typing import Any

from core.tool import SideEffectLevel, report_run_error
from core.tool_framework import tool
from core.tool_framework.utils import build_mcp_tool_listing, unavailable_response
from integrations.signoz.mcp import (
    SigNozMCPConfig,
    SigNozMCPRefused,
    call_signoz_mcp_tool,
    describe_signoz_mcp_error,
    list_signoz_mcp_tools,
)

_COMPONENT = "integrations.signoz.tools.signoz_mcp_tool"
_NOT_CONFIGURED = "SigNoz MCP is not configured. Set SIGNOZ_MCP_URL."


def _signoz_mcp_available(sources: dict[str, dict]) -> bool:
    signoz = sources.get("signoz", {})
    return bool(
        signoz.get("mcp_url") and (signoz.get("connection_verified") or signoz.get("api_key"))
    )


def _signoz_mcp_extract_params(sources: dict[str, dict]) -> dict[str, Any]:
    signoz = sources.get("signoz", {})
    return {
        "mcp_url": str(signoz.get("mcp_url", "")).strip(),
        "api_key": str(signoz.get("api_key", "")).strip(),
    }


def _config(mcp_url: str | None, api_key: str | None) -> SigNozMCPConfig | None:
    if not mcp_url:
        return None
    return SigNozMCPConfig(url=mcp_url, api_key=api_key or "")


@tool(
    name="list_signoz_tools",
    display_name="SigNoz MCP tools",
    source="signoz",
    side_effect_level=SideEffectLevel.READ_ONLY,
    concurrency_safe=True,
    tags=("observability", "alerts", "metrics", "logs", "traces"),
    description=(
        "List the read-only tools of the SigNoz MCP server: alert rules and their firing "
        "history, dashboards, services, field keys and values, log and trace search and "
        "aggregation, metrics, and builder queries with any filter, group-by and aggregation. "
        "Returns names and short descriptions; pass name_filter (e.g. 'alert metrics') and "
        "include_schema=true to get the input schema of the tool you mean to call."
    ),
    use_cases=[
        "Finding the SigNoz tool that reads an alert rule's query, or its firing history",
        "Getting the input schema of signoz_execute_builder_query before running a rule's query",
    ],
    input_schema={
        "type": "object",
        "properties": {
            "name_filter": {
                "type": "string",
                "description": "Space- or comma-separated terms, e.g. 'alert history builder'.",
            },
            "include_schema": {
                "type": "boolean",
                "description": "Include input schemas; narrow with name_filter first.",
            },
        },
        "required": [],
    },
    is_available=_signoz_mcp_available,
    extract_params=_signoz_mcp_extract_params,
)
def list_signoz_tools(
    name_filter: str | None = None,
    include_schema: bool = False,
    mcp_url: str | None = None,
    api_key: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """List the read-only tools of the configured SigNoz MCP server."""
    config = _config(mcp_url, api_key)
    if config is None:
        return {**unavailable_response("signoz_mcp", _NOT_CONFIGURED), "tools": []}
    try:
        tools = list_signoz_mcp_tools(config)
    except Exception as err:
        report_run_error(
            err,
            tool_name="list_signoz_tools",
            source="signoz",
            component=_COMPONENT,
            method="list_signoz_mcp_tools",
        )
        return {**unavailable_response("signoz_mcp", describe_signoz_mcp_error(err)), "tools": []}
    listing = build_mcp_tool_listing(
        tools,
        name_filter=(name_filter or "").strip() or None,
        include_schema=bool(include_schema),
        filter_example="alert metrics builder",
    )
    return {"source": "signoz_mcp", "available": True, **listing}


@tool(
    name="call_signoz_tool",
    display_name="SigNoz MCP call",
    source="signoz",
    side_effect_level=SideEffectLevel.READ_ONLY,
    concurrency_safe=True,
    tags=("observability", "alerts", "metrics", "logs", "traces"),
    description=(
        "Call a read-only SigNoz MCP tool by name (see list_signoz_tools), e.g. "
        "signoz_get_alert for a rule's query and threshold, signoz_get_alert_history, or "
        "signoz_execute_builder_query to run a rule's own query with its filters, grouped by "
        "host or any other attribute. Timestamps are Unix milliseconds."
    ),
    use_cases=[
        "Reading the alert rule that fired: its query, filters, threshold and window",
        "Running the rule's own query, or a breakdown of it by host, service or another label",
        "Searching or aggregating logs and traces with attribute filters",
    ],
    requires=["tool_name"],
    input_schema={
        "type": "object",
        "properties": {
            "tool_name": {"type": "string", "description": "A tool from list_signoz_tools."},
            "arguments": {"type": "object", "description": "The tool's arguments."},
        },
        "required": ["tool_name"],
    },
    is_available=_signoz_mcp_available,
    extract_params=_signoz_mcp_extract_params,
)
def call_signoz_tool(
    tool_name: str | None = None,
    arguments: dict[str, object] | None = None,
    mcp_url: str | None = None,
    api_key: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Call one read-only SigNoz MCP tool by name."""
    name = (tool_name or "").strip()
    arguments = arguments or {}
    if not name:
        return unavailable_response("signoz_mcp", "tool_name is required.", arguments=arguments)
    config = _config(mcp_url, api_key)
    if config is None:
        return unavailable_response(
            "signoz_mcp", _NOT_CONFIGURED, tool_name=name, arguments=arguments
        )
    try:
        result = call_signoz_mcp_tool(config, name, arguments)
    except SigNozMCPRefused as err:
        return unavailable_response("signoz_mcp", str(err), tool_name=name, arguments=arguments)
    except Exception as err:
        report_run_error(
            err,
            tool_name="call_signoz_tool",
            source="signoz",
            component=_COMPONENT,
            method="call_signoz_mcp_tool",
            extras={"mcp_tool": name},
        )
        return unavailable_response(
            "signoz_mcp", describe_signoz_mcp_error(err), tool_name=name, arguments=arguments
        )
    if result.get("is_error"):
        return unavailable_response(
            "signoz_mcp",
            str(result.get("text") or "SigNoz MCP tool call failed."),
            tool_name=name,
            arguments=arguments,
        )
    return {
        "source": "signoz_mcp",
        "available": True,
        "tool": name,
        "arguments": arguments,
        "text": result.get("text", ""),
        "structured_content": result.get("structured_content"),
    }
