"""Registry entrypoint for list_signoz_tools and call_signoz_tool."""

from __future__ import annotations

from integrations.signoz.tools.signoz_mcp_tool.tool import (
    _signoz_mcp_available,
    call_signoz_tool,
    list_signoz_tools,
)

TOOL_MODULES = ("tool",)

__all__ = ["TOOL_MODULES", "_signoz_mcp_available", "call_signoz_tool", "list_signoz_tools"]
