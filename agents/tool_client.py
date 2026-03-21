"""Shared MCP tool execution helpers for agent stages."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def execute_mcp_tool(function_name: str, arguments: dict[str, Any]) -> str:
    """Execute one local MCP tool call and normalize its text output."""

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(PROJECT_ROOT, "mcp_server.py")],
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(function_name, arguments)
    except Exception as exc:
        return (
            f"Tool Error: MCP execution failed for {function_name} ({exc}). "
            "Please rely solely on internal PDF context."
        )

    content = getattr(result, "content", None)
    if not content:
        return (
            f"Tool Error: MCP execution failed for {function_name} (empty tool response). "
            "Please rely solely on internal PDF context."
        )

    text_parts: list[str] = []
    for item in content:
        text_value = getattr(item, "text", None)
        if text_value:
            text_parts.append(str(text_value))
            continue

        if isinstance(item, dict) and item.get("text"):
            text_parts.append(str(item["text"]))

    if text_parts:
        return "\n".join(text_parts)

    return str(content)


def execute_mcp_tool_sync(function_name: str, arguments: dict[str, Any]) -> str:
    """Synchronous wrapper used by the Celery worker and benchmark paths."""

    return asyncio.run(execute_mcp_tool(function_name, arguments))
