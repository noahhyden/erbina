"""Small shared helpers for the erbina test suite.

We deliberately avoid pytest-asyncio (or any pytest plugin): every test is a
plain synchronous function. Async interactions with the in-memory FastMCP
client are driven through `call_tool` below, which wraps the coroutine in
`asyncio.run(...)`. This keeps the run command to just:

    uv run --with pytest --with fastmcp --with pyyaml pytest tests/ -v
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import Client

import server


def _extract(result: Any) -> Any:
    """Best-effort unwrap of a FastMCP tool-call result into plain data.

    FastMCP has returned different shapes across versions; prefer the parsed
    structured payload when available, then fall back to raw text content.
    """
    for attr in ("data", "structured_content"):
        val = getattr(result, attr, None)
        if val is not None:
            return val
    content = getattr(result, "content", None)
    if content:
        block = content[0]
        text = getattr(block, "text", None)
        if text is not None:
            return text
    return result


def call_tool(name: str, args: dict[str, Any] | None = None) -> Any:
    """Call a tool over an in-memory Client(server.mcp) and return plain data.

    Synchronous by design — runs its own event loop so no async plugin is
    needed. Mirrors the smoke-test pattern documented in CONTRIBUTING.md.
    """

    async def _go() -> Any:
        async with Client(server.mcp) as client:
            res = await client.call_tool(name, args or {})
            return _extract(res)

    return asyncio.run(_go())


def list_tool_names() -> set[str]:
    """The exact set of registered tool names, via the in-memory client."""

    async def _go() -> set[str]:
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            return {t.name for t in tools}

    return asyncio.run(_go())
