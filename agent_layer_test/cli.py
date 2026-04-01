from __future__ import annotations

import argparse
import json
import sys
from json import JSONDecoder
from pathlib import Path
from typing import Any, Iterable

from agent_layer_test.mcp_surface import ToolSurface, list_tools
from agent_layer_test.models import SuiteSpec
from agent_layer_test.planner_prompt import PlannerPrompt
from agent_layer_test.reporting import (
    CaseResult,
    print_details,
    print_summary,
    save_report_md,
    save_run_json,
)
from agent_layer_test.runners.opencode_runner import run_opencode


def _load_suite(path: Path) -> SuiteSpec:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SuiteSpec.model_validate(raw)


def _extract_first_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    s = text.strip()
    if not s:
        return None, "empty assistant output"

    decoder = JSONDecoder()
    for i, ch in enumerate(s):
        if ch not in "[{":
            continue
        try:
            obj, _end = decoder.raw_decode(s[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj, None
    return None, "could not parse a JSON object from assistant output"


def _required_keys(schema: dict[str, Any]) -> set[str]:
    req = schema.get("required")
    if isinstance(req, list):
        return {str(x) for x in req}
    return set()


def _allowed_tools_summary(tool_surface: dict[str, ToolSurface]) -> str:
    # Keep this concise: names + required keys only.
    lines: list[str] = []
    for name in sorted(tool_surface.keys()):
        req = sorted(_required_keys(tool_surface[name].input_schema))
        suffix = ", ".join(req) if req else "(none)"
        lines.append(f"- {name}: {suffix}")
    return "\n".join(lines)


def _validate_plan(
    *,
    plan: dict[str, Any],
    tool_surface: dict[str, ToolSurface],
    max_tool_calls: int,
) -> list[str]:
    errors: list[str] = []
    calls = plan.get("tool_calls")
    if not isinstance(calls, list):
        return ["plan.tool_calls must be a list"]
    if len(calls) > max_tool_calls:
        errors.append(f"plan.tool_calls must be <= {max_tool_calls}")

    for idx, c in enumerate(calls):
        if not isinstance(c, dict):
            errors.append(f"tool_calls[{idx}] must be an object")
            continue
        name = c.get("name")
        args = c.get("arguments")
        if not isinstance(name, str) or not name:
            errors.append(f"tool_calls[{idx}].name must be a non-empty string")
            continue
        if name not in tool_surface:
            errors.append(f"tool_calls[{idx}].name is not a known MCP tool: {name}")
            continue
        if not isinstance(args, dict):
            errors.append(f"tool_calls[{idx}].arguments must be an object")
            continue

        required = _required_keys(tool_surface[name].input_schema)
        missing = [k for k in sorted(required) if k not in args]
        if missing:
            errors.append(
                f"tool_calls[{idx}] missing required arguments for {name}: {', '.join(missing)}"
            )
    return errors


def _iter_selected_workflows(suite: SuiteSpec, ids: set[str] | None) -> Iterable[tuple[str, str, str]]:
    for wf in suite.workflows:
        if ids is not None and wf.id not in ids:
            continue
        for pv in wf.prompt_variants:
            yield f"{wf.id}/{pv.id}", "workflow", pv.prompt


def _iter_selected_tool_prompts(suite: SuiteSpec, names: set[str] | None) -> Iterable[tuple[str, str, str]]:
    for tp in suite.tool_prompts:
        if names is not None and tp.tool_name not in names:
            continue
        yield tp.tool_name, "tool", tp.prompt


def _parse_ids(raw: list[str] | None) -> set[str] | None:
    if not raw:
        return None
    out: set[str] = set()
    for part in raw:
        for tok in part.split(","):
            t = tok.strip()
            if t:
                out.add(t)
    return out or None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent-layer-test")
    p.add_argument(
        "--suite",
        default=str(Path(__file__).resolve().parent / "suite.json"),
        help="Path to suite.json",
    )
    p.add_argument("--agent", default=None, help="Agent backend to run (v1: opencode)")
    p.add_argument("--dry-run", action="store_true", help="Print commands, do not execute")
    p.add_argument("--save-run", default=None, help="Write JSON record to this path")
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any case has parse/validation/tool-exec violations",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-case parsed plan and errors to stdout",
    )
    p.add_argument(
        "--report-md",
        default=None,
        help="Write a markdown report to this path",
    )

    sub = p.add_subparsers(dest="mode", required=True)

    pw = sub.add_parser("workflows", help="Run workflow prompt variants")
    pw.add_argument("--id", action="append", default=None, help="Workflow id(s), comma-separated")
    pw.add_argument(
        "--id-range",
        default=None,
        help="Inclusive range like 5-8 (workflows only)",
    )

    pt = sub.add_parser("tool-prompts", help="Run per-tool prompts")
    pt.add_argument(
        "--tool",
        action="append",
        default=None,
        help="Tool name(s), comma-separated",
    )

    args = p.parse_args(argv)
    suite_path = Path(args.suite)
    suite = _load_suite(suite_path)

    agent_name = args.agent or suite.agents.default
    if agent_name != "opencode":
        print(f"Unsupported agent backend in v1: {agent_name}", file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parents[1]

    tool_surface = list_tools(argv=["stellarbridge-mcp"], cwd=str(repo_root))
    allowed_tools = _allowed_tools_summary(tool_surface)
    max_calls = suite.planner_constraints.max_tool_calls
    opencode_backend = suite.agents.opencode

    if args.mode == "workflows":
        ids = _parse_ids(args.id)
        if args.id_range:
            try:
                a_str, b_str = str(args.id_range).split("-", 1)
                a = int(a_str.strip(), 10)
                b = int(b_str.strip(), 10)
            except Exception:
                print("Invalid --id-range. Expected like 5-8", file=sys.stderr)
                return 2
            if a > b:
                a, b = b, a
            range_ids = {str(i) for i in range(a, b + 1)}
            ids = range_ids if ids is None else (ids & range_ids)
        cases = list(_iter_selected_workflows(suite, ids))
    else:
        names = _parse_ids(args.tool)
        cases = list(_iter_selected_tool_prompts(suite, names))

    results: list[CaseResult] = []
    for case_id, kind, user_prompt in cases:
        rendered = PlannerPrompt(
            case_id=case_id,
            kind=kind,
            user_prompt=user_prompt,
            max_tool_calls=max_calls,
            allowed_tools=allowed_tools,
        ).render()

        if args.dry_run:
            print(f"[{kind} {case_id}] {' '.join(opencode_backend.argv)} <PROMPT>")
            continue

        run = run_opencode(
            argv_prefix=opencode_backend.argv,
            prompt=rendered,
            timeout_seconds=opencode_backend.timeout_seconds,
            cwd=str(repo_root),
        )

        parsed, parse_err = _extract_first_json(run.assistant_text)
        validation_errors: list[str] = []
        if parsed is not None:
            validation_errors = _validate_plan(
                plan=parsed,
                tool_surface=tool_surface,
                max_tool_calls=max_calls,
            )

            calls = parsed.get("tool_calls")
            if isinstance(calls, list):
                for c in calls:
                    if isinstance(c, dict) and isinstance(c.get("name"), str):
                        ts = tool_surface.get(c["name"])
                        if ts is not None:
                            c.setdefault("tool_description", ts.description)

        results.append(
            CaseResult(
                case_id=case_id,
                kind=kind,
                exit_code=run.exit_code,
                duration_seconds=run.duration_seconds,
                tool_execution_events=run.tool_use_events,
                assistant_text=run.assistant_text,
                parsed_plan=parsed,
                parse_error=parse_err,
                validation_errors=validation_errors,
            )
        )

    if args.dry_run:
        return 0

    print_summary(results)
    if args.verbose:
        print_details(results)
    if args.save_run:
        save_run_json(args.save_run, results)
    if args.report_md:
        save_report_md(args.report_md, suite_path=str(suite_path), results=results)

    if not args.strict:
        return 0

    any_bad = False
    for r in results:
        if r.exit_code != 0:
            any_bad = True
        if r.tool_execution_events and suite.planner_constraints.forbid_tool_execution:
            any_bad = True
        if r.parsed_plan is None:
            any_bad = True
        if r.validation_errors:
            any_bad = True
    return 1 if any_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
