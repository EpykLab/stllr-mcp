"""Registry matches the canonical MCP tool list (no live API required)."""

from __future__ import annotations

from tests.integration.mcp_tool_cases import EXPECTED_MCP_TOOL_NAMES
from tests.integration_live.live_tool_registry import LIVE_TOOL_SPECS


def test_live_tool_registry_covers_all_expected_tools() -> None:
    assert {s.tool_name for s in LIVE_TOOL_SPECS} == EXPECTED_MCP_TOOL_NAMES
