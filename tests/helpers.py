"""Shared test helpers (see AGENTS.d/140: the suite is plugin-free and synchronous)."""
from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import Client

import server


def call_tool(name: str, args: dict[str, Any] | None = None) -> Any:
    """Call a tool over an in-memory Client(server.mcp) and return plain data, running its own event loop."""

    async def _go() -> Any:
        async with Client(server.mcp) as client:
            res = await client.call_tool(name, args or {})
            return res.data

    return asyncio.run(_go())


def list_tool_names() -> set[str]:
    """The exact set of registered tool names, via the in-memory client."""

    async def _go() -> set[str]:
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            return {t.name for t in tools}

    return asyncio.run(_go())
