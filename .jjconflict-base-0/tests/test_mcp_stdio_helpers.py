"""Tests for MCP stdio integration helpers."""

from __future__ import annotations

from types import SimpleNamespace

from tests.integration.mcp_stdio_helpers import (
    first_json_from_tool_content,
    json_from_tool_result,
)


def test_first_json_empty_content_is_none() -> None:
    assert first_json_from_tool_content([]) is None


def test_audit_tool_empty_content_maps_to_empty_array() -> None:
    """FastMCP may omit text when audit list tools return []."""
    assert json_from_tool_result("audit_get_audit_logs", []) == []
    assert json_from_tool_result("audit_get_audit_logs_for_file", []) == []


def test_delete_tool_empty_content_stays_none() -> None:
    assert json_from_tool_result("drive_delete_drive_object", []) is None


def test_text_block_json_array() -> None:
    block = SimpleNamespace(type="text", text='[{"id": "1"}]')
    assert first_json_from_tool_content([block]) == [{"id": "1"}]


def test_empty_text_block_not_confused_with_missing_content() -> None:
    block = SimpleNamespace(type="text", text="")
    assert first_json_from_tool_content([block]) is None
