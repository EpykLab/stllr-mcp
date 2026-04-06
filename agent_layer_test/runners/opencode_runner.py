from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OpencodeRun:
    exit_code: int
    duration_seconds: float
    stdout: str
    stderr: str
    events: list[dict[str, Any]]
    tool_use_events: list[dict[str, Any]]
    assistant_text: str


def _parse_json_lines(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            out.append(json.loads(s))
        except json.JSONDecodeError:
            # Keep tolerant if stray non-JSON output appears.
            continue
    return out


def _extract_assistant_text(events: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for e in events:
        if e.get("type") != "text":
            continue
        part = e.get("part") or {}
        t = part.get("text")
        if isinstance(t, str):
            chunks.append(t)
    return "\n".join(chunks).strip()


def _extract_tool_use_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in events:
        if e.get("type") == "tool_use":
            out.append(e)
            continue
        part = e.get("part")
        if isinstance(part, dict) and part.get("type") == "tool":
            out.append(e)
    return out


def run_opencode(*, argv_prefix: list[str], prompt: str, timeout_seconds: int, cwd: str) -> OpencodeRun:
    started = time.time()
    proc = subprocess.run(
        [*argv_prefix, prompt],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    duration = time.time() - started
    events = _parse_json_lines(proc.stdout)
    tool_use_events = _extract_tool_use_events(events)
    assistant_text = _extract_assistant_text(events)
    return OpencodeRun(
        exit_code=proc.returncode,
        duration_seconds=duration,
        stdout=proc.stdout,
        stderr=proc.stderr,
        events=events,
        tool_use_events=tool_use_events,
        assistant_text=assistant_text,
    )
