## The suite is plugin-free and synchronous

No pytest plugin and no async test: helpers.call_tool wraps the in-memory FastMCP Client in asyncio.run, so the run command stays `uv run --with pytest --with fastmcp --with pyyaml pytest tests/`; adding pytest-asyncio breaks that.
