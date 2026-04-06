from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class CaseResult:
    case_id: str
    kind: str
    exit_code: int
    duration_seconds: float
    tool_execution_events: list[dict[str, Any]]
    assistant_text: str
    parsed_plan: dict[str, Any] | None
    parse_error: str | None
    validation_errors: list[str]


_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_STLLR_KEY = re.compile(r"\bstllr_[A-Za-z0-9+/=]{10,}\b")
_URL = re.compile(r"https?://\S+")


def _sanitize(obj: Any) -> Any:
    """Basic redaction for artifacts (defense-in-depth).

    We prefer to avoid collecting sensitive tool outputs at all, but if an agent
    violates the contract and executes tools, stdout may contain PII or presigned
    URLs. This function makes run artifacts safer to share.
    """
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    if isinstance(obj, str):
        s = obj
        s = _EMAIL.sub("user@example.com", s)
        s = _STLLR_KEY.sub("stllr_<REDACTED>", s)
        # Redact full URLs (presigned URLs commonly include secrets).
        s = _URL.sub("<REDACTED_URL>", s)
        return s
    return obj


def print_summary(results: list[CaseResult]) -> None:
    for r in results:
        tool_exec = "VIOLATION" if r.tool_execution_events else "ok"
        plan = "ok" if r.parsed_plan is not None else "invalid"
        val = "ok" if not r.validation_errors else f"{len(r.validation_errors)} error(s)"
        print(
            f"[{r.kind} {r.case_id}] exit={r.exit_code} dur={r.duration_seconds:.2f}s plan={plan} tools={tool_exec} validate={val}"
        )


def print_details(results: list[CaseResult]) -> None:
    for r in results:
        print(f"\n== {r.kind} {r.case_id} ==")
        if r.parse_error:
            print(f"parse_error: {r.parse_error}")
        if r.tool_execution_events:
            print(f"tool_execution_events: {len(r.tool_execution_events)} (VIOLATION)")
        if r.validation_errors:
            print("validation_errors:")
            for e in r.validation_errors:
                print(f"- {e}")
        if r.parsed_plan is not None:
            safe = _sanitize(r.parsed_plan)
            print("plan:")
            print(json.dumps(safe, indent=2, sort_keys=True))


def save_run_json(path: str, results: list[CaseResult]) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": [_sanitize(asdict(r)) for r in results],
    }
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(record, indent=2, sort_keys=True))
        f.write("\n")


def save_report_md(path: str, *, suite_path: str, results: list[CaseResult]) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []
    lines.append(f"# Agent-Layer Test Report")
    lines.append("")
    lines.append(f"- Timestamp: `{ts}`")
    lines.append(f"- Suite: `{suite_path}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Case | Exit | Duration (s) | JSON plan | Tool exec | Validation |")
    lines.append("| --- | ---: | ---: | --- | --- | --- |")
    for r in results:
        plan = "ok" if r.parsed_plan is not None else "invalid"
        tool_exec = "VIOLATION" if r.tool_execution_events else "ok"
        val = "ok" if not r.validation_errors else f"{len(r.validation_errors)} error(s)"
        lines.append(
            f"| `{r.kind} {r.case_id}` | `{r.exit_code}` | `{r.duration_seconds:.2f}` | `{plan}` | `{tool_exec}` | `{val}` |"
        )

    lines.append("")
    lines.append("## Details")
    for r in results:
        lines.append("")
        lines.append(f"### {r.kind} {r.case_id}")
        lines.append("")
        if r.parse_error:
            lines.append(f"- parse_error: `{_sanitize(r.parse_error)}`")
        if r.tool_execution_events:
            lines.append(f"- tool_execution_events: `{len(r.tool_execution_events)}` (VIOLATION)")
        if r.validation_errors:
            lines.append("- validation_errors:")
            for e in r.validation_errors:
                lines.append(f"  - `{_sanitize(e)}`")
        lines.append("")
        if r.parsed_plan is None:
            lines.append("No JSON plan parsed.")
        else:
            safe = _sanitize(r.parsed_plan)
            lines.append("```json")
            lines.append(json.dumps(safe, indent=2, sort_keys=True))
            lines.append("```")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")
