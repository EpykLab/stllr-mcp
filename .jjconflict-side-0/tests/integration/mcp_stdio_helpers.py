"""Helpers for MCP stdio integration tests."""

from __future__ import annotations

import json
from typing import Any


def first_json_from_tool_content(content: list[Any]) -> Any:
    """Parse JSON from MCP tool result (text block or LC-style content list)."""
    text = _first_text_content(content)
    if text is None or text == "":
        return None
    return json.loads(text)


def json_from_tool_result(
    tool_name: str,
    content: list[Any],
    *,
    is_error: bool = False,
) -> Any:
    """Like :func:`first_json_from_tool_content`, but fixes FastMCP omitting a text
    block when audit list tools return an empty Python ``[]`` (``content`` is then
    empty). Tools that return no serializable body may also yield empty
    ``content`` (``None``) except ``audit_get_audit_logs*`` (treated as ``[]``).
    """
    parsed = first_json_from_tool_content(content)
    if parsed is not None:
        return parsed
    if is_error:
        return None
    if not content and tool_name.startswith("audit_get_audit_logs"):
        return []
    return None


def _first_text_content(content: list[Any]) -> str | None:
    for block in content:
        if getattr(block, "type", None) == "text":
            return str(block.text)
    return None
