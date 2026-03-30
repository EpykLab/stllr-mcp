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


def _first_text_content(content: list[Any]) -> str | None:
    for block in content:
        if getattr(block, "type", None) == "text":
            return str(block.text)
    return None
