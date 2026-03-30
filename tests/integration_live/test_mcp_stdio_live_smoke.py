"""Smoke tests: MCP over stdio against a real Stellarbridge API (opt-in)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.integration.mcp_stdio_helpers import first_json_from_tool_content


@pytest.mark.live_api
async def test_live_stdio_list_tools(
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
    assert "drive_list_drive_objects" in names
    assert "projects_list_projects" in names
    assert len(names) >= 10


@pytest.mark.live_api
async def test_live_projects_list_projects(
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
            result = await session.call_tool("projects_list_projects", {})

    assert not result.isError
    data = first_json_from_tool_content(result.content)
    assert isinstance(data, list)


@pytest.mark.live_api
async def test_live_drive_list_objects_when_project_id_set(
    real_stellarbridge_env: dict[str, str],
    repo_root: Path,
) -> None:
    """Optional: set STELLARBRIDGE_TEST_PROJECT_ID to a project you can access."""
    raw = os.environ.get("STELLARBRIDGE_TEST_PROJECT_ID", "").strip()
    if not raw:
        pytest.skip("Set STELLARBRIDGE_TEST_PROJECT_ID to run drive list against a real project.")
    project_id = int(raw)

    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "stellarbridge_mcp"],
        env=real_stellarbridge_env,
        cwd=str(repo_root),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "drive_list_drive_objects",
                {"project_id": project_id},
            )

    assert not result.isError
    data = first_json_from_tool_content(result.content)
    assert isinstance(data, list)

