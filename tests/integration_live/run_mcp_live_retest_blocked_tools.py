"""Live MCP retest for the tool subset previously tracked as blocked.

This is a *runner script* (not a pytest test) intended for QA retest runs
against the real backend via stdio MCP. It writes a markdown report to a local
path (ignored by git) so results can be shared out-of-band.

Why a script:
- Live tool invocations may legitimately fail/skips depending on backend
  readiness; we want a report without forcing `pytest` failures on opt-in runs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


RETEST_TOOL_NAMES: tuple[str, ...] = (
    "drive_attach_policy_to_object",
    "drive_delete_drive_object",
    "drive_detach_policy_from_object",
    "drive_get_drive_download_url",
    "drive_share_drive_object",
    "projects_delete_project",
    "requests_delete_file_request",
    "requests_get_file_request",
    "transfers_add_transfer_to_drive",
    "transfers_cancel_multipart_upload",
    "transfers_delete_transfer",
    "transfers_get_multipart_presigned_urls",
    "transfers_get_transfer_public_info",
    "transfers_share_transfer",
)


_URL = re.compile(r"https?://\S+")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_STLLR_KEY = re.compile(r"\bstllr_[A-Za-z0-9+/=]{10,}\b")


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _redact_urls(text: str) -> str:
    return _URL.sub("<REDACTED_URL>", text)


def _redact_pii(text: str) -> str:
    # Defense-in-depth: avoid leaking emails/keys in reports.
    s = text
    s = _EMAIL.sub("user@example.com", s)
    s = _STLLR_KEY.sub("stllr_<REDACTED>", s)
    s = _redact_urls(s)
    return s


def _redact_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_obj(x) for x in obj]
    if isinstance(obj, str):
        return _redact_pii(obj)
    return obj


def _first_text_block(content: list[Any]) -> str | None:
    # mcp-sdk returns content blocks; FastMCP tool results commonly have one text block.
    for block in content:
        if getattr(block, "type", None) == "text":
            return str(block.text)
    return None


def _parse_json_from_tool_content(content: list[Any]) -> Any:
    txt = _first_text_block(content)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


@dataclass(frozen=True)
class StepResult:
    tool_name: str
    arguments: dict[str, Any]
    ok: bool
    parsed_json: Any
    raw_text_preview: str


async def _call(session: ClientSession, tool_name: str, arguments: dict[str, Any]) -> StepResult:
    result = await session.call_tool(tool_name, arguments)
    raw = _first_text_block(result.content) or ""
    parsed = _parse_json_from_tool_content(result.content)
    preview = raw if len(raw) <= 800 else raw[:800] + "..."
    return StepResult(
        tool_name=tool_name,
        arguments=arguments,
        ok=not bool(getattr(result, "isError", False)),
        parsed_json=_redact_obj(parsed),
        raw_text_preview=_redact_pii(preview),
    )


def _deep_get(obj: Any, *path: str) -> Any:
    cur = obj
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _extract_int_id(obj: Any) -> int | None:
    # Common shapes: {"id": 123} or {"data": {"id": 123}}
    if isinstance(obj, dict):
        v = obj.get("id")
        if isinstance(v, int):
            return v
        v2 = _deep_get(obj, "data", "id")
        if isinstance(v2, int):
            return v2
    return None


def _extract_str_id(obj: Any, *keys: str) -> str | None:
    if not isinstance(obj, dict):
        return None
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v:
            return v
        v2 = _deep_get(obj, "data", k)
        if isinstance(v2, str) and v2:
            return v2
    return None


async def _run(*, repo_root: Path, recipient_email: str | None) -> list[StepResult]:
    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "stellarbridge_mcp"],
        env=dict(os.environ),
        cwd=str(repo_root),
    )

    steps: list[StepResult] = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Discover a project id for disposable Drive actions.
            pr_raw = await _call(session, "projects_list_projects", {})
            projects = pr_raw.parsed_json
            project_id: int | None = None
            project_name: str | None = None
            # Live API shape: {"data": {"projects": [...]}, "error": null}
            arr = _deep_get(projects, "data", "projects")
            if isinstance(arr, list) and arr:
                first = arr[0]
                if isinstance(first, dict) and isinstance(first.get("id"), int):
                    project_id = int(first["id"])
                    n = first.get("name")
                    project_name = str(n) if isinstance(n, str) else None
                pr = StepResult(
                    tool_name=pr_raw.tool_name,
                    arguments=pr_raw.arguments,
                    ok=pr_raw.ok,
                    parsed_json={
                        "project_count": len(arr),
                        "selected_project_id": project_id,
                        "selected_project_name": _redact_obj(project_name),
                    },
                    raw_text_preview=pr_raw.raw_text_preview,
                )
            else:
                pr = StepResult(
                    tool_name=pr_raw.tool_name,
                    arguments=pr_raw.arguments,
                    ok=pr_raw.ok,
                    parsed_json={"project_count": 0, "selected_project_id": None},
                    raw_text_preview=pr_raw.raw_text_preview,
                )
            steps.append(pr)

            # Drive: create a disposable placeholder file to exercise download/share/delete.
            placeholder_id: int | None = None
            if project_id is not None:
                cr = await _call(
                    session,
                    "drive_create_drive_file_placeholder",
                    {
                        "project_id": project_id,
                        "name": f"live-mcp-retest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.txt",
                        "mime_type": "text/plain",
                    },
                )
                steps.append(cr)
                placeholder_id = _extract_int_id(cr.parsed_json)

            if placeholder_id is not None:
                steps.append(await _call(session, "drive_get_drive_download_url", {"object_id": placeholder_id}))

                if recipient_email:
                    steps.append(
                        await _call(
                            session,
                            "drive_share_drive_object",
                            {"object_id": placeholder_id, "recipient_email": recipient_email},
                        )
                    )

                # Clean up
                steps.append(await _call(session, "drive_delete_drive_object", {"object_id": placeholder_id}))

            # Requests: create -> (if id returned) get/delete.
            if recipient_email:
                rr = await _call(
                    session,
                    "requests_create_file_request",
                    {
                        "title": f"live-mcp-retest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                        "recipient_email": recipient_email,
                    },
                )
                steps.append(rr)

                request_id = _extract_str_id(
                    rr.parsed_json,
                    "request_id",
                    "requestId",
                    "upload_id",
                    "uploadId",
                    "id",
                )

                if request_id:
                    steps.append(await _call(session, "requests_get_file_request", {"request_id": request_id}))
                    steps.append(await _call(session, "requests_delete_file_request", {"request_id": request_id}))

            # Transfers: initialize -> presigned URLs -> cancel.
            init = await _call(
                session,
                "transfers_initialize_multipart_upload",
                {
                    "file_name": f"live-mcp-retest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bin",
                    "size_bytes": 9_000_000,
                },
            )
            steps.append(init)
            upload_id: str | None = None
            file_key: str | None = None
            if isinstance(init.parsed_json, dict):
                upload_id = _extract_str_id(init.parsed_json, "fileId", "uploadId", "file_id", "upload_id")
                file_key = _extract_str_id(init.parsed_json, "fileKey", "file_key")

            if upload_id and file_key:
                steps.append(
                    await _call(
                        session,
                        "transfers_get_multipart_presigned_urls",
                        {"upload_id": upload_id, "file_key": file_key, "parts": 3},
                    )
                )
                steps.append(
                    await _call(
                        session,
                        "transfers_cancel_multipart_upload",
                        {"upload_id": upload_id, "file_key": file_key},
                    )
                )

            # Transfers: upload a small fixture via multipart helper, then retest transfer tools.
            fixture = (repo_root / Path("tests/fixtures/uploads/multipart_upload.bin")).resolve()
            if fixture.is_file():
                transfer_name = f"live-mcp-retest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bin"
                up = await _call(
                    session,
                    "transfers_upload_transfer_multipart_file",
                    {"file_path": str(fixture), "file_name": transfer_name},
                )
                steps.append(up)

                transfer_id = _extract_str_id(up.parsed_json, "tid", "transfer_id", "transferId", "id")

                # Fallback: list transfers and locate by exact generated name.
                if transfer_id is None:
                    lt = await _call(session, "transfers_list_transfers", {})
                    arr = lt.parsed_json
                    transfers: list[dict[str, Any]] | None = None
                    if isinstance(arr, list):
                        transfers = [x for x in arr if isinstance(x, dict)]
                    else:
                        tarr = _deep_get(arr, "data", "transfers")
                        if isinstance(tarr, list):
                            transfers = [x for x in tarr if isinstance(x, dict)]

                    matched_tid: str | None = None
                    sample_tids: list[str] = []
                    if transfers:
                        for item in transfers:
                            if not isinstance(item, dict):
                                continue
                            if item.get("name") == transfer_name:
                                v = item.get("tid") or item.get("transfer_id") or item.get("id")
                                if isinstance(v, str) and v:
                                    matched_tid = v
                                    break
                        for item in transfers[:5]:
                            if not isinstance(item, dict):
                                continue
                            v = item.get("tid") or item.get("transfer_id") or item.get("id")
                            if isinstance(v, str) and v:
                                sample_tids.append(v)

                    steps.append(
                        StepResult(
                            tool_name=lt.tool_name,
                            arguments=lt.arguments,
                            ok=lt.ok,
                            parsed_json={
                                "transfer_count": (len(transfers) if transfers else None),
                                "matched_name": transfer_name,
                                "matched_tid": matched_tid,
                                "sample_tids": sample_tids,
                            },
                            raw_text_preview=lt.raw_text_preview,
                        )
                    )
                    transfer_id = matched_tid

                if transfer_id:
                    steps.append(await _call(session, "transfers_get_transfer_public_info", {"transfer_id": transfer_id}))

                    if recipient_email:
                        steps.append(
                            await _call(
                                session,
                                "transfers_share_transfer",
                                {"transfer_id": transfer_id, "recipient_email": recipient_email},
                            )
                        )

                    if project_id is not None:
                        steps.append(
                            await _call(
                                session,
                                "transfers_add_transfer_to_drive",
                                {"transfer_id": transfer_id, "project_id": project_id},
                            )
                        )

                    steps.append(await _call(session, "transfers_delete_transfer", {"transfer_id": transfer_id}))

    return steps


def _write_report(*, path: Path, steps: list[StepResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []
    lines.append("# MCP Live QA Retest Results")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{ts}`")
    lines.append(f"- API URL: `{os.environ.get('STELLARBRIDGE_API_URL','').strip()}`")
    lines.append(f"- STELLARBRIDGE_LIVE_ALLOW_MUTATIONS: `{os.environ.get('STELLARBRIDGE_LIVE_ALLOW_MUTATIONS','')}`")
    lines.append("")
    lines.append("## Summary (Retest Tool Set)")
    lines.append("")
    lines.append("| Tool | Result | Notes |")
    lines.append("| --- | --- | --- |")

    by_tool: dict[str, StepResult] = {s.tool_name: s for s in steps}
    notes: dict[str, str] = {}
    # Static skip notes for tools that require out-of-band IDs.
    notes.setdefault(
        "drive_attach_policy_to_object",
        "Requires STELLARBRIDGE_TEST_POLICY_ID and object permissions; not exercised in this workflow.",
    )
    notes.setdefault(
        "drive_detach_policy_from_object",
        "Requires STELLARBRIDGE_TEST_ATTACHMENT_ID; not exercised in this workflow.",
    )
    notes.setdefault(
        "projects_delete_project",
        "Requires an empty disposable project id; not exercised in this workflow.",
    )

    # If create_file_request didn't return an id, we can't retest get/delete.
    if "requests_create_file_request" in by_tool and "requests_get_file_request" not in by_tool:
        notes["requests_get_file_request"] = "No request_id obtained from requests_create_file_request in this run."
    if "requests_create_file_request" in by_tool and "requests_delete_file_request" not in by_tool:
        notes["requests_delete_file_request"] = "No request_id obtained from requests_create_file_request in this run."

    # If transfer upload didn't yield a transfer id, downstream transfer tools are skipped.
    if "transfers_upload_transfer_multipart_file" in by_tool and "transfers_get_transfer_public_info" not in by_tool:
        notes["transfers_get_transfer_public_info"] = "No transfer_id obtained (upload failed or response lacked tid)."
    if "transfers_upload_transfer_multipart_file" in by_tool and "transfers_share_transfer" not in by_tool:
        notes["transfers_share_transfer"] = "No transfer_id obtained (upload failed or response lacked tid)."
    if "transfers_upload_transfer_multipart_file" in by_tool and "transfers_add_transfer_to_drive" not in by_tool:
        notes["transfers_add_transfer_to_drive"] = "No transfer_id obtained (upload failed or response lacked tid)."
    if "transfers_upload_transfer_multipart_file" in by_tool and "transfers_delete_transfer" not in by_tool:
        notes["transfers_delete_transfer"] = "No transfer_id obtained (upload failed or response lacked tid)."

    for name in RETEST_TOOL_NAMES:
        s = by_tool.get(name)
        if s is None:
            lines.append(f"| `{name}` | `SKIP` | {notes.get(name, '')} |")
        else:
            lines.append(
                f"| `{name}` | `{('PASS' if s.ok else 'FAIL')}` | {notes.get(name, '')} |"
            )

    lines.append("")
    lines.append("## Details")
    lines.append("")
    lines.append("This report includes setup calls (e.g. create placeholder/request/upload) to obtain IDs for the retest tools.")
    lines.append("Only the tool outputs below are sanitized (URLs/emails/keys redacted).")
    for s in steps:
        lines.append("")
        lines.append(f"### `{s.tool_name}`")
        lines.append("")
        lines.append(f"- Result: `{('PASS' if s.ok else 'FAIL')}`")
        lines.append(f"- Arguments: `{json.dumps(_redact_obj(s.arguments), sort_keys=True)}`")
        if s.parsed_json is not None:
            lines.append("")
            lines.append("Response (parsed JSON, sanitized):")
            lines.append("```json")
            lines.append(json.dumps(s.parsed_json, indent=2, sort_keys=True))
            lines.append("```")
        elif s.raw_text_preview:
            lines.append("")
            lines.append("Response (text preview, sanitized):")
            lines.append("```text")
            lines.append(s.raw_text_preview)
            lines.append("```")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mcp-live-retest")
    p.add_argument(
        "--out",
        default="tests/retest_results/mcp_live_retest_2026-04-06.md",
        help="Write markdown report to this path (default: tests/retest_results/...).",
    )
    args = p.parse_args(argv)

    if not _truthy_env("STELLARBRIDGE_LIVE_API"):
        print("Set STELLARBRIDGE_LIVE_API=1 to run live retest.", file=sys.stderr)
        return 2
    if not os.environ.get("STELLARBRIDGE_API_URL") or not os.environ.get("STELLARBRIDGE_API_KEY"):
        print("STELLARBRIDGE_API_URL and STELLARBRIDGE_API_KEY must be set.", file=sys.stderr)
        return 2
    if not _truthy_env("STELLARBRIDGE_LIVE_ALLOW_MUTATIONS"):
        print(
            "Set STELLARBRIDGE_LIVE_ALLOW_MUTATIONS=1 to run this retest (creates/deletes disposable resources).",
            file=sys.stderr,
        )
        return 2

    recipient = os.environ.get("STELLARBRIDGE_TEST_RECIPIENT_EMAIL")
    if recipient:
        recipient = recipient.strip()
    if not recipient:
        print(
            "STELLARBRIDGE_TEST_RECIPIENT_EMAIL is not set. Share/request/share-transfer steps will be skipped.",
            file=sys.stderr,
        )
        recipient = None

    repo_root = Path(__file__).resolve().parents[2]
    steps = asyncio_run(_run(repo_root=repo_root, recipient_email=recipient))
    out_path = Path(str(args.out)).expanduser().resolve()
    _write_report(path=out_path, steps=steps)
    print(str(out_path))
    # Return non-zero only if a retest tool was executed and failed.
    executed_retest = [s for s in steps if s.tool_name in set(RETEST_TOOL_NAMES)]
    any_fail = any((not s.ok) for s in executed_retest)
    return 1 if any_fail else 0


def asyncio_run(coro: Any) -> Any:
    # Minimal local runner to avoid adding dependencies.
    try:
        import asyncio

        return asyncio.run(coro)
    except RuntimeError:
        # If already in an event loop, fall back.
        import anyio

        return anyio.run(lambda: coro)


if __name__ == "__main__":
    raise SystemExit(main())
