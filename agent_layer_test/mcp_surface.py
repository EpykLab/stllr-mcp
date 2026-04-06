from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSurface:
    name: str
    description: str
    input_schema: dict[str, Any]


async def _list_tools_async(*, command: str, args: list[str], env: dict[str, str], cwd: str) -> dict[str, ToolSurface]:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(command=command, args=args, env=env, cwd=cwd)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()

    out: dict[str, ToolSurface] = {}
    for t in listed.tools:
        out[t.name] = ToolSurface(
            name=t.name,
            description=t.description or "",
            input_schema=t.inputSchema or {},
        )
    return out


def list_tools(*, argv: list[str], cwd: str, extra_env: dict[str, str] | None = None) -> dict[str, ToolSurface]:
    if not argv:
        raise ValueError("mcp server argv must not be empty")

    env = {
        # Ensure FastMCP doesn't spam banners into stderr during harness runs.
        "FASTMCP_SHOW_SERVER_BANNER": "false",
        "FASTMCP_CHECK_FOR_UPDATES": "off",
        "FASTMCP_LOG_ENABLED": "false",
        "FASTMCP_LOG_LEVEL": "ERROR",
        # These should not be required for tools/list, but set safe placeholders.
        "STELLARBRIDGE_API_URL": "http://127.0.0.1:9",
        "STELLARBRIDGE_API_KEY": "integration-test-api-key",
    }
    if extra_env:
        env.update({k: v for k, v in extra_env.items() if v is not None})

    command = argv[0]
    args = argv[1:]
    return asyncio.run(_list_tools_async(command=command, args=args, env=env, cwd=cwd))
