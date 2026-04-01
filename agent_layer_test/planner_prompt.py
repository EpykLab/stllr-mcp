from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class PlannerPrompt:
    case_id: str
    kind: str  # "workflow" | "tool"
    user_prompt: str
    max_tool_calls: int
    allowed_tools: str

    def render(self) -> str:
        # The whole point of this harness is to test planning, not execution.
        return (
            "You are being evaluated in a planning-only test.\n"
            "\n"
            "Rules:\n"
            "- Do NOT execute any tools. Do NOT call MCP tools.\n"
            "- Produce a plan that a later execution step could run.\n"
            "- Tool names MUST be MCP tool names as returned by tools/list (e.g. drive_list_drive_objects, projects_list_projects).\n"
            "  Do NOT prefix tool names (no 'functions.', no 'stellarbridge_').\n"
            "- For any tool call you include, you MUST include all required argument KEYS for that tool.\n"
            "  If you don't know a value, still include the key with a placeholder string value.\n"
            "- You MUST ONLY use the allowed Stellarbridge MCP tools listed below. Do not use local file tools.\n"
            "\n"
            "Allowed Stellarbridge MCP tools (name -> required argument keys):\n"
            + self.allowed_tools
            + "\n\n"
            "- If required IDs (project_id/object_id/etc.) are unknown, use placeholders and ask questions.\n"
            "\n"
            "Output format (STRICT): Return JSON ONLY (no markdown, no code fences, no extra text).\n"
            "The JSON MUST be an object with these keys:\n"
            f"- case_id: string (use {json.dumps(self.case_id)})\n"
            f"- kind: string (use {json.dumps(self.kind)})\n"
            f"- tool_calls: array of 0..{self.max_tool_calls} objects\n"
            "  each: {\"name\": string, \"arguments\": object}\n"
            "- questions: array of strings (may be empty)\n"
            "- assumptions: array of strings (may be empty)\n"
            "\n"
            "User request:\n"
            + self.user_prompt.strip()
        )
