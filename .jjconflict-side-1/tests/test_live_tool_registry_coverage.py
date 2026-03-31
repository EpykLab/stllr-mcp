"""Registry matches the canonical MCP tool list (no live API required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.mcp_tool_cases import EXPECTED_MCP_TOOL_NAMES
from tests.integration_live.live_tool_registry import LIVE_TOOL_SPECS


def test_live_tool_registry_covers_all_expected_tools() -> None:
    assert {s.tool_name for s in LIVE_TOOL_SPECS} == EXPECTED_MCP_TOOL_NAMES


def test_requests_get_file_request_skips_without_request_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("STELLARBRIDGE_TEST_REQUEST_ID", raising=False)
    spec = next(s for s in LIVE_TOOL_SPECS if s.tool_name == "requests_get_file_request")
    args, reason = spec(tmp_path)
    assert args is None
    assert "STELLARBRIDGE_TEST_REQUEST_ID" in reason
    assert "stllr#408" in reason or "public/upload" in reason
