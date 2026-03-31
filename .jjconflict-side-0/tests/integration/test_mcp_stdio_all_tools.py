"""MCP stdio integration: every HTTP-backed tool matches the Stellarbridge API contract."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pytest_httpserver import HTTPServer

from .mcp_stdio_helpers import json_from_tool_result
from .mcp_tool_cases import (
    EXPECTED_MCP_TOOL_NAMES,
    TOOL_HTTP_CASES,
    ToolHttpCase,
)


@pytest.mark.integration
async def test_stdio_list_tools_matches_expected_surface(
    httpserver: HTTPServer,
    stellarbridge_api_env: dict[str, str],
    repo_root: Path,
) -> None:
    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "stellarbridge_mcp"],
        env=stellarbridge_api_env,
        cwd=str(repo_root),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
    names = {t.name for t in listed.tools}
    assert names == EXPECTED_MCP_TOOL_NAMES


@pytest.mark.integration
@pytest.mark.parametrize("case", TOOL_HTTP_CASES, ids=lambda c: c.tool_name)
async def test_stdio_tool_invocation_http_contract(
    case: ToolHttpCase,
    httpserver: HTTPServer,
    stellarbridge_api_env: dict[str, str],
    repo_root: Path,
) -> None:
    """Each tool triggers exactly one expected API request; JSON round-trip matches."""
    case.register(httpserver)
    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "stellarbridge_mcp"],
        env=stellarbridge_api_env,
        cwd=str(repo_root),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(case.tool_name, case.arguments)

    assert not result.isError
    data = json_from_tool_result(case.tool_name, result.content)
    assert data == case.expected_json
    assert len(httpserver.log) == 1
