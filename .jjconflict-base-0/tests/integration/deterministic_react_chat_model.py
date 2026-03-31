"""Fake chat model that implements ``bind_tools`` for LangChain ``create_agent`` tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool


class DeterministicReactChatModel(FakeMessagesListChatModel):
    """Cycles through scripted messages; ``bind_tools`` matches ``ChatOpenAI``-style binding."""

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | BaseTool | Any],
        *,
        tool_choice: dict | str | bool | None = None,
        strict: bool | None = None,
        **kwargs: Any,
    ):
        formatted = [convert_to_openai_tool(t, strict=strict) for t in tools]
        return self.bind(tools=formatted, tool_choice=tool_choice, **kwargs)
