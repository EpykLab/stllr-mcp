"""Smoke tests: MCP over stdio against a real Stellarbridge API (opt-in).

Per-tool ``tools/call`` coverage lives in ``test_mcp_stdio_live_all_tools.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.integration.mcp_tool_cases import EXPECTED_MCP_TOOL_NAMES


@pytest.mark.live_api
async def test_live_stdio_list_tools_matches_expected_surface(
    real_stellarbridge_env: dict[str, str],
    repo_root: Path,
) -> None:
    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "stellarbridge_mcp"],
        env=real_stellarbridge_env,
        cwd=str(repo_root),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
    names = {t.name for t in listed.tools}
    assert names == EXPECTED_MCP_TOOL_NAMES

