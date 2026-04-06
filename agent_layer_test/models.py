from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PromptVariant(BaseModel):
    id: str
    prompt: str


class WorkflowSpec(BaseModel):
    id: str
    name: str
    description: str
    success_criteria: list[str] = Field(default_factory=list)
    prompt_variants: list[PromptVariant]

    @field_validator("prompt_variants")
    @classmethod
    def _exactly_three_prompts(cls, v: list[PromptVariant]) -> list[PromptVariant]:
        if len(v) != 3:
            raise ValueError("workflow.prompt_variants must have exactly 3 items")
        return v


class ToolPromptSpec(BaseModel):
    tool_name: str
    prompt: str


class OpencodeAgentBackend(BaseModel):
    type: Literal["opencode"] = "opencode"

    # argv prefix (prompt appended as final argument)
    argv: list[str] = Field(
        default_factory=lambda: [
            "opencode",
            "run",
            "--format",
            "json",
            "--model",
            "openai/gpt-5.2",
            "--variant",
            "high",
        ]
    )

    timeout_seconds: int = 180


class AgentsConfig(BaseModel):
    default: str = "opencode"
    opencode: OpencodeAgentBackend = Field(default_factory=OpencodeAgentBackend)

    # Future agents (Cursor/Claude/Goose) will be added once we have verified
    # non-interactive CLI command templates.


class PlannerConstraints(BaseModel):
    max_tool_calls: int = 3
    forbid_tool_execution: bool = True
    require_strict_json_output: bool = True


class SuiteSpec(BaseModel):
    schema_version: int = 1
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    planner_constraints: PlannerConstraints = Field(default_factory=PlannerConstraints)
    workflows: list[WorkflowSpec]
    tool_prompts: list[ToolPromptSpec]
