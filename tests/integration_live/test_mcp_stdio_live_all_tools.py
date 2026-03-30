"""Parametrized ``tools/call`` for every registered MCP tool against a real API (opt-in)."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.integration.mcp_stdio_helpers import first_json_from_tool_content

from .live_tool_registry import LIVE_TOOL_SPECS, LiveToolSpec


@pytest.mark.live_api
@pytest.mark.parametrize("spec", LIVE_TOOL_SPECS, ids=lambda s: s.tool_name)
async def test_live_stdio_call_tool(
    spec: LiveToolSpec,
    real_stellarbridge_env: dict[str, str],
    repo_root: Path,
) -> None:
    args, skip_reason = spec(repo_root)
    if args is None:
        pytest.skip(skip_reason)

    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "stellarbridge_mcp"],
        env=real_stellarbridge_env,
        cwd=str(repo_root),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(spec.tool_name, args)

    assert not result.isError, (
        f"{spec.tool_name} failed: {first_json_from_tool_content(result.content)!r}"
    )
    first_json_from_tool_content(result.content)
