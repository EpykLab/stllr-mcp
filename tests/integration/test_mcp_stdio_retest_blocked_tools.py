"""Focused MCP stdio retest for tool cases previously marked blocked.

This test is intentionally narrow: it re-runs the deterministic mock-HTTP
contract checks for the subset of tools that were marked `- [~]` in the local
tracking doc `tests/mcp_testing (1).md`.

The tracking doc itself is intentionally untracked; this test is the durable,
reviewable artifact we merge to `master`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pytest_httpserver import HTTPServer

from .mcp_stdio_helpers import json_from_tool_result
from .mcp_tool_cases import TOOL_HTTP_CASES, ToolHttpCase


# Keep ordering stable for pytest output readability.
RETEST_TOOL_NAMES: tuple[str, ...] = (
    "drive_attach_policy_to_object",
    "drive_delete_drive_object",
    "drive_detach_policy_from_object",
    "drive_get_drive_download_url",
    "drive_share_drive_object",
    "projects_delete_project",
    "requests_delete_file_request",
    "requests_get_file_request",
    "transfers_add_transfer_to_drive",
    "transfers_cancel_multipart_upload",
    "transfers_delete_transfer",
    "transfers_get_multipart_presigned_urls",
    "transfers_get_transfer_public_info",
    "transfers_share_transfer",
)


def _select_cases() -> tuple[ToolHttpCase, ...]:
    selected = [c for c in TOOL_HTTP_CASES if c.tool_name in set(RETEST_TOOL_NAMES)]
    selected.sort(key=lambda c: RETEST_TOOL_NAMES.index(c.tool_name))
    return tuple(selected)


RETEST_CASES = _select_cases()


@pytest.mark.integration
def test_retest_case_set_matches_expected_tools() -> None:
    got = {c.tool_name for c in RETEST_CASES}
    expected = set(RETEST_TOOL_NAMES)
    assert got == expected


@pytest.mark.integration
@pytest.mark.parametrize("case", RETEST_CASES, ids=lambda c: c.tool_name)
async def test_stdio_tool_invocation_http_contract_retest_subset(
    case: ToolHttpCase,
    httpserver: HTTPServer,
    stellarbridge_api_env: dict[str, str],
    repo_root: Path,
) -> None:
    """Same contract as the full suite, limited to the retest subset."""
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
