"""Integration tests: LangChain create_agent + langchain-mcp-adapters against the real stdio server."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from pytest_httpserver import HTTPServer

from .deterministic_react_chat_model import DeterministicReactChatModel


@pytest.mark.integration
async def test_react_agent_invokes_drive_list_tool_deterministically(
    httpserver: HTTPServer,
    stellarbridge_api_env: dict[str, str],
    repo_root: Path,
) -> None:
    """Fixed fake LLM emits a tool call; graph runs ToolNode against the real MCP server."""
    payload = [{"id": 1, "name": "a.txt", "type": "FILE"}]
    httpserver.expect_oneshot_request(
        "/api/v1/objects",
        method="GET",
        query_string={"project_id": "1"},
    ).respond_with_data(
        json.dumps(payload),
        content_type="application/json",
        status=200,
    )

    llm = DeterministicReactChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "drive_list_drive_objects",
                        "args": {"project_id": 1},
                        "id": "tool_call_integration_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Listed project objects."),
        ]
    )

    connection: dict[str, object] = {
        "transport": "stdio",
        "command": "uv",
        "args": ["run", "python", "-m", "stellarbridge_mcp"],
        "env": stellarbridge_api_env,
        "cwd": str(repo_root),
    }
    client = MultiServerMCPClient({"stllr": connection})
    tools = await client.get_tools(server_name="stllr")
    agent = create_agent(llm, tools)

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="List drive objects for project 1.")]},
        config={"recursion_limit": 10},
    )

    messages = result["messages"]
    tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
    assert tool_msgs, "expected at least one ToolMessage from MCP"
    assert tool_msgs[0].name == "drive_list_drive_objects"
    body = tool_msgs[0].content
    if isinstance(body, str):
        parsed = json.loads(body)
    elif isinstance(body, list) and body and isinstance(body[0], dict):
        text = next((b["text"] for b in body if b.get("type") == "text"), None)
        assert text is not None
        parsed = json.loads(text)
    else:
        parsed = body
    assert parsed == payload
    assert len(httpserver.log) == 1
