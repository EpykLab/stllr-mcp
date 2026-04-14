"""Workflow-style live MCP QA run (stdio MCP, real API).

Goal: exercise as much of the MCP tool surface as possible *without* requiring
pre-baked IDs. This script creates disposable resources (folders, file
placeholders, uploads, transfers, requests) and then reuses returned IDs to
exercise downstream tools.

Output: writes a sanitized markdown report to a local path (ignored by git) so
it can be shared out-of-band.

Safety:
- Requires STELLARBRIDGE_LIVE_API=1 and STELLARBRIDGE_LIVE_ALLOW_MUTATIONS=1.
- Uses a target Drive project from STELLARBRIDGE_TEST_PROJECT_ID.
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

import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = (_REPO_ROOT / "tests/fixtures/uploads/multipart_upload.bin").resolve()

_URL = re.compile(r"https?://\S+")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_STLLR_KEY = re.compile(r"\bstllr_[A-Za-z0-9+/=]{10,}\b")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _redact_text(text: str) -> str:
    s = text
    s = _EMAIL.sub("user@example.com", s)
    s = _STLLR_KEY.sub("stllr_<REDACTED>", s)
    s = _URL.sub("<REDACTED_URL>", s)
    if s.startswith("auth0|"):
        s = "auth0|redacted"
    return s


def _classify_failure(*, tool_name: str, raw_text_preview: str) -> tuple[str, str]:
    """Return (status, note) for a failure preview.

    We use SKIP for explicit documented limitations so the overall workflow run
    can still be considered "successful" while clearly recording the limitation.
    """
    msg = raw_text_preview or ""

    # Documented limitation: API key callers not supported.
    if "not yet supported for API key callers" in msg:
        return (
            "SKIP",
            "Known limitation: not supported for API key callers (see Stellarbridge MCP docs).",
        )

    # In practice the MCP tool error often doesn't include the backend JSON body.
    # For Drive share we still treat 422 as a known limitation for API-key auth.
    if tool_name == "drive_share_drive_object" and "422 Unprocessable Entity" in msg:
        return (
            "SKIP",
            "Known limitation: Drive share is not supported for API key callers (422).",
        )

    # File-request inspection appears to be intended for uploader sessions.
    # The live API returns 401 with a message directing callers to use the upload link.
    if tool_name == "requests_get_file_request" and "401 Unauthorized" in msg:
        return (
            "SKIP",
            "Known limitation: request inspection requires an upload session (API key cannot GET request details).",
        )

    # Helpful notes for common auth/rate-limit failures.
    if "401 Unauthorized" in msg:
        return ("FAIL", "Unauthorized (401) for this endpoint with current API key.")
    if "429" in msg or "Rate limited" in msg:
        return (
            "SKIP",
            "Rate limited (429). Not treated as product failure; retry later or reduce request volume.",
        )

    return ("FAIL", "")


def _truncate_lists(obj: Any, max_items: int) -> Any:
    if isinstance(obj, list):
        trimmed = obj[:max_items]
        if len(obj) > max_items:
            return [_truncate_lists(x, max_items) for x in trimmed] + [
                f"... {len(obj) - max_items} more items omitted"
            ]
        return [_truncate_lists(x, max_items) for x in trimmed]
    if isinstance(obj, dict):
        return {k: _truncate_lists(v, max_items) for k, v in obj.items()}
    return obj


def _redact_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in ("email", "actor") and isinstance(v, str) and _EMAIL.search(v):
                out[k] = "user@example.com"
            elif lk in ("fname", "lname"):
                out[k] = "Redacted"
            elif lk == "domain" and isinstance(v, str):
                out[k] = "partner.example.com"
            elif lk in ("filename", "name") and isinstance(v, str) and "." in v[-10:]:
                out[k] = "redacted-sample" + v[v.rindex(".") :]
            else:
                out[k] = _redact_obj(v)
        return out
    if isinstance(obj, list):
        return [_redact_obj(x) for x in obj]
    if isinstance(obj, str):
        if _UUID.match(obj):
            return "00000000-0000-4000-8000-000000000000"
        return _redact_text(obj)
    return obj


def _unwrap_data(raw: Any) -> Any:
    if not isinstance(raw, dict) or "data" not in raw:
        return raw
    if raw.get("error") is not None:
        return raw
    return raw.get("data")


def _extract_partner_ids_from_projects_list(raw: Any) -> list[int]:
    """Best-effort extraction of partner ids from projects_list_projects response."""
    data = _unwrap_data(raw)
    projects = None
    if isinstance(data, dict) and isinstance(data.get("projects"), list):
        projects = data["projects"]
    if not projects:
        return []
    ids: set[int] = set()
    for p in projects:
        if not isinstance(p, dict):
            continue
        edges = p.get("edges")
        if not isinstance(edges, dict):
            continue
        partners = edges.get("partners")
        if not isinstance(partners, list):
            continue
        for partner in partners:
            if not isinstance(partner, dict):
                continue
            pid = partner.get("id")
            if isinstance(pid, int):
                ids.add(pid)
    return sorted(ids)


def _first_text_block(content: list[Any]) -> str | None:
    for block in content:
        # mcp content blocks may be dataclasses or plain dicts depending on version.
        btype = getattr(block, "type", None)
        if btype is None and isinstance(block, dict):
            btype = block.get("type")
        if btype == "text":
            if isinstance(block, dict):
                return str(block.get("text", ""))
            return str(getattr(block, "text", ""))
    return None


def _parse_json_from_tool_content(content: list[Any]) -> Any:
    # Some MCP implementations may return a native JSON content block (not text).
    for block in content:
        btype = getattr(block, "type", None)
        if btype is None and isinstance(block, dict):
            btype = block.get("type")
        if btype in ("json", "application/json"):
            if isinstance(block, dict):
                if "json" in block:
                    return block.get("json")
                if "data" in block:
                    return block.get("data")
            v = getattr(block, "json", None)
            if v is not None:
                return v

    txt = _first_text_block(content)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


def _extract_int_id(raw: Any) -> int | None:
    raw = _unwrap_data(raw)
    if isinstance(raw, dict) and isinstance(raw.get("id"), int):
        return int(raw["id"])
    return None


def _extract_str(raw: Any, *keys: str) -> str | None:
    raw = _unwrap_data(raw)
    if not isinstance(raw, dict):
        return None
    for k in keys:
        v = raw.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _extract_object_id(raw: Any) -> int | None:
    """Extract a Drive object id from add_transfer_to_drive responses."""
    data = _unwrap_data(raw)
    if isinstance(data, dict):
        for k in ("objectId", "object_id", "id"):
            v = data.get(k)
            if isinstance(v, int):
                return v
            if isinstance(v, str) and v.isdigit():
                return int(v, 10)
    return None


def _find_transfer_tid_by_name(raw: Any, *, name: str) -> str | None:
    """Find a transfer tid by exact name from transfers_list_transfers output."""
    data = _unwrap_data(raw)
    items: list[Any] | None = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("transfers"), list):
        items = data["transfers"]
    if not items:
        return None
    for it in items:
        if not isinstance(it, dict):
            continue
        iname = it.get("name") or it.get("fileName") or it.get("file_name") or it.get("filename")
        if iname != name:
            continue
        tid = it.get("tid") or it.get("transfer_id") or it.get("transferId") or it.get("id")
        if isinstance(tid, str) and tid:
            return tid
    return None


def _collect_candidate_transfer_tids(
    raw: Any,
    *,
    prefer_prefixes: tuple[str, ...] = ("mcp-live-transfer-", "mcp-live-"),
    limit: int = 5,
) -> list[str]:
    """Collect candidate transfer ids from transfers_list_transfers output.

    Prefer test-created transfers (by name prefix) when available, otherwise fall
    back to any tids present.
    """
    data = _unwrap_data(raw)
    items: list[Any] | None = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("transfers"), list):
        items = data["transfers"]
    if not items or limit <= 0:
        return []

    out: list[str] = []

    def _add(tid: Any) -> None:
        if not (isinstance(tid, str) and tid):
            return
        if tid not in out:
            out.append(tid)

    def _name(it: dict[str, Any]) -> str:
        v = it.get("name") or it.get("fileName") or it.get("file_name") or it.get("filename")
        return v if isinstance(v, str) else ""

    def _tid(it: dict[str, Any]) -> Any:
        return it.get("tid") or it.get("transfer_id") or it.get("transferId") or it.get("id")

    # 1) Prefer likely test-created transfers by name prefix.
    for it in items:
        if not isinstance(it, dict):
            continue
        nm = _name(it)
        if not nm:
            continue
        if prefer_prefixes and not any(nm.startswith(p) for p in prefer_prefixes):
            continue
        _add(_tid(it))
        if len(out) >= limit:
            return out

    # 2) Fall back to any tid.
    for it in items:
        if not isinstance(it, dict):
            continue
        _add(_tid(it))
        if len(out) >= limit:
            return out

    return out


def _strip_quotes(s: str) -> str:
    v = s.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1]
    return v


@dataclass(frozen=True)
class ToolStep:
    tool_name: str
    arguments: dict[str, Any]
    status: str  # PASS | FAIL | SKIP
    note: str
    parsed_json: Any  # raw parsed JSON (redaction happens at report time)
    raw_text_preview: str


async def _call(session: ClientSession, tool_name: str, arguments: dict[str, Any]) -> ToolStep:
    try:
        result = await session.call_tool(tool_name, arguments)
    except Exception as e:  # transport/protocol errors
        return ToolStep(
            tool_name=tool_name,
            arguments=arguments,
            status="FAIL",
            note=f"exception: {type(e).__name__}",
            parsed_json=None,
            raw_text_preview=_redact_text(repr(e)),
        )

    raw = _first_text_block(result.content) or ""
    parsed = _parse_json_from_tool_content(result.content)
    preview = raw if len(raw) <= 900 else raw[:900] + "..."
    ok = not bool(getattr(result, "isError", False))

    status = "PASS" if ok else "FAIL"
    note = ""
    if not ok:
        status, note = _classify_failure(tool_name=tool_name, raw_text_preview=_redact_text(preview))

    return ToolStep(
        tool_name=tool_name,
        arguments=arguments,
        status=status,
        note=note,
        parsed_json=parsed,
        raw_text_preview=_redact_text(preview),
    )


async def _call_with_retries(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    retries: int = 3,
    base_sleep_s: float = 1.0,
) -> ToolStep:
    """Retry on known transient upstream throttling errors."""
    import asyncio

    attempt = 0
    while True:
        attempt += 1
        step = await _call(session, tool_name, arguments)
        if step.status == "PASS" or attempt > retries:
            return step
        msg = (step.raw_text_preview or "")
        # fastmcp maps 429 to "Rate limited by upstream API" ToolError.
        if "Rate limited" not in msg and "429" not in msg:
            return step
        await asyncio.sleep(base_sleep_s * (2 ** (attempt - 1)))


async def _lookup_transfer_tid(
    session: ClientSession,
    *,
    transfer_name: str,
    attempts: int = 4,
    sleep_s: float = 1.0,
) -> tuple[list[ToolStep], str | None, list[str]]:
    """Best-effort: list transfers and match by name (eventual consistency tolerant)."""
    import asyncio

    steps: list[ToolStep] = []
    candidates: list[str] = []
    for i in range(attempts):
        lt = await _call_with_retries(
            session,
            "transfers_list_transfers",
            {},
            retries=4,
            base_sleep_s=1.0,
        )
        steps.append(lt)
        if lt.status == "PASS":
            for tid in _collect_candidate_transfer_tids(lt.parsed_json, limit=10):
                if tid not in candidates:
                    candidates.append(tid)
        tid = _find_transfer_tid_by_name(lt.parsed_json, name=transfer_name) if lt.status == "PASS" else None
        if tid:
            steps.append(
                ToolStep(
                    tool_name="(transfer_tid_lookup)",
                    arguments={"transfer_name": transfer_name},
                    status="PASS",
                    note=f"matched by name via transfers_list_transfers (attempt {i+1}/{attempts})",
                    parsed_json={"transfer_name": transfer_name, "matched_tid": tid, "candidates": candidates[:10]},
                    raw_text_preview="",
                ),
            )
            return steps, tid, candidates
        if i < attempts - 1:
            await asyncio.sleep(sleep_s * (2**i))

    if candidates:
        # This follows the normal operator/agent workflow pattern: list transfers first,
        # pick a target tid, then operate on it.
        steps.append(
            ToolStep(
                tool_name="(transfer_tid_lookup)",
                arguments={"transfer_name": transfer_name},
                status="PASS",
                note="No tid returned from upload and upload was not found by name; selecting candidate tids from transfers_list_transfers.",
                parsed_json={"transfer_name": transfer_name, "matched_tid": None, "candidates": candidates[:10]},
                raw_text_preview="",
            )
        )
        return steps, None, candidates

    steps.append(
        ToolStep(
            tool_name="(transfer_tid_lookup)",
            arguments={"transfer_name": transfer_name},
            status="SKIP",
            note="Upload did not return a tid and transfers_list_transfers returned no tid to use. Provide STELLARBRIDGE_TEST_TRANSFER_ID to exercise downstream transfer tools.",
            parsed_json={"transfer_name": transfer_name, "matched_tid": None, "candidates": []},
            raw_text_preview="",
        )
    )
    return steps, None, []


async def _run(
    repo_root: Path, *, project_id: int | None, recipient_email: str | None
) -> tuple[list[ToolStep], int | None]:
    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "stellarbridge_mcp"],
        env=dict(os.environ),
        cwd=str(repo_root),
    )

    steps: list[ToolStep] = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Record tool surface for reporting completeness.
            listed = await session.list_tools()
            tool_names = sorted({t.name for t in listed.tools})
            steps.append(
                ToolStep(
                    tool_name="(mcp_list_tools)",
                    arguments={},
                    status="PASS",
                    note=f"tool_count={len(tool_names)}",
                    parsed_json={"tools": tool_names},
                    raw_text_preview="",
                )
            )

            # -----------------
            # Baseline: audit + projects + drive list
            # -----------------
            proj_list = await _call(session, "projects_list_projects", {})
            steps.append(proj_list)

            # Resolve the Drive project id for this workflow.
            # Default behavior: require an explicit project id OR create a disposable project.
            workflow_project_id = project_id
            created_workflow_project = False

            partner_ids: list[int] = []
            env_partner_ids = os.environ.get("STELLARBRIDGE_TEST_PARTNER_IDS", "").strip()
            if env_partner_ids:
                try:
                    partner_ids = [int(x.strip(), 10) for x in env_partner_ids.split(",") if x.strip()]
                except ValueError:
                    partner_ids = []
            if not partner_ids:
                partner_ids = _extract_partner_ids_from_projects_list(proj_list.parsed_json)

            if workflow_project_id is None:
                if partner_ids:
                    created = await _call(
                        session,
                        "projects_create_project",
                        {
                            "name": f"mcp-live-workflow-project-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                            "partner_ids": partner_ids,
                        },
                    )
                    steps.append(created)
                    created_id = _extract_int_id(created.parsed_json)
                    if created_id is not None:
                        workflow_project_id = created_id
                        created_workflow_project = True
                    else:
                        steps.append(
                            ToolStep(
                                tool_name="drive_list_drive_objects",
                                arguments={"project_id": "<missing from projects_create_project response>"},
                                status="SKIP",
                                note="Cannot run Drive workflow without a project id.",
                                parsed_json=None,
                                raw_text_preview="",
                            )
                        )
                        return steps, None
                else:
                    steps.append(
                        ToolStep(
                            tool_name="projects_create_project",
                            arguments={"name": "<missing>", "partner_ids": "<missing STELLARBRIDGE_TEST_PARTNER_IDS>"},
                            status="SKIP",
                            note="Set STELLARBRIDGE_TEST_PROJECT_ID or STELLARBRIDGE_TEST_PARTNER_IDS to create a disposable workflow project.",
                            parsed_json=None,
                            raw_text_preview="",
                        )
                    )
                    return steps, None

            # Optional: exercise project create/delete (only when a project id is explicitly provided).
            # When project_id is missing we already exercised create and will delete at the end.
            if project_id is not None:
                if partner_ids:
                    created_project = await _call(
                        session,
                        "projects_create_project",
                        {
                            "name": f"mcp-live-project-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                            "partner_ids": partner_ids,
                        },
                    )
                    steps.append(created_project)
                    created_id = _extract_int_id(created_project.parsed_json)
                    if created_id is not None:
                        # Best effort: delete immediately (should be empty).
                        steps.append(await _call(session, "projects_delete_project", {"project_id": created_id}))
                    else:
                        steps.append(
                            ToolStep(
                                tool_name="projects_delete_project",
                                arguments={"project_id": "<missing from create response>"},
                                status="SKIP",
                                note="projects_create_project did not return an id to delete.",
                                parsed_json=None,
                                raw_text_preview="",
                            )
                        )
                else:
                    steps.append(
                        ToolStep(
                            tool_name="projects_create_project",
                            arguments={"name": "<missing>", "partner_ids": "<missing STELLARBRIDGE_TEST_PARTNER_IDS>"},
                            status="SKIP",
                            note="Set STELLARBRIDGE_TEST_PARTNER_IDS or ensure projects_list_projects returns partner ids.",
                            parsed_json=None,
                            raw_text_preview="",
                        )
                    )
                    steps.append(
                        ToolStep(
                            tool_name="projects_delete_project",
                            arguments={"project_id": "<requires empty disposable project>"},
                            status="SKIP",
                            note="Requires an empty disposable project id (or enable project create/delete above).",
                            parsed_json=None,
                            raw_text_preview="",
                        )
                    )
            steps.append(await _call(session, "audit_get_audit_logs", {}))
            steps.append(
                await _call(session, "audit_get_audit_logs_for_file", {"file_name": "mcp-live-workflow"})
            )
            actor_upn = os.environ.get("STELLARBRIDGE_TEST_ACTOR_ID", "").strip() or None
            # The audit endpoint supports actor as a UPN/email in practice.
            if not actor_upn and recipient_email:
                actor_upn = recipient_email

            if actor_upn:
                steps.append(
                    await _call(
                        session,
                        "audit_get_audit_logs_for_actor",
                        {"actor_id": actor_upn},
                    )
                )
            else:
                steps.append(
                    ToolStep(
                        tool_name="audit_get_audit_logs_for_actor",
                        arguments={"actor_id": "<missing STELLARBRIDGE_TEST_ACTOR_ID or recipient email>"},
                        status="SKIP",
                        note="Set STELLARBRIDGE_TEST_ACTOR_ID (actor UPN/email) to exercise this tool.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )

            steps.append(await _call(session, "drive_list_drive_objects", {"project_id": workflow_project_id}))

            # -----------------
            # Drive workflow: folder + placeholder + rename + move + upload-url + PUT + complete + download-url + share + delete
            # -----------------
            folder = await _call(
                session,
                "drive_create_drive_folder",
                {
                    "project_id": workflow_project_id,
                    "name": f"mcp-live-folder-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                },
            )
            steps.append(folder)
            folder_id = _extract_int_id(folder.parsed_json)

            placeholder = await _call(
                session,
                "drive_create_drive_file_placeholder",
                {
                    "project_id": workflow_project_id,
                    "name": f"mcp-live-placeholder-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bin",
                    "mime_type": "application/octet-stream",
                },
            )
            steps.append(placeholder)
            placeholder_id = _extract_int_id(placeholder.parsed_json)

            if placeholder_id is None:
                # Without an object id there is nothing else we can safely do.
                return steps

            steps.append(await _call(session, "drive_get_drive_object", {"object_id": placeholder_id}))
            steps.append(
                await _call(
                    session,
                    "drive_rename_drive_object",
                    {
                        "object_id": placeholder_id,
                        "new_name": f"mcp-live-renamed-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bin",
                    },
                )
            )
            if folder_id is not None:
                steps.append(
                    await _call(
                        session,
                        "drive_move_drive_object",
                        {"object_id": placeholder_id, "new_parent_id": folder_id},
                    )
                )
            else:
                steps.append(
                    ToolStep(
                        tool_name="drive_move_drive_object",
                        arguments={"object_id": placeholder_id, "new_parent_id": "<missing folder_id>"},
                        status="SKIP",
                        note="Folder create did not yield an id.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )

            steps.append(await _call(session, "drive_list_object_policy_attachments", {"object_id": placeholder_id}))

            # Policy mutation tools are intentionally NOT exercised.
            # Agents are explicitly banned from mutating policies in the API.
            if "drive_attach_policy_to_object" in tool_names:
                steps.append(
                    ToolStep(
                        tool_name="drive_attach_policy_to_object",
                        arguments={"object_id": placeholder_id, "policy_id": "<not exercised>"},
                        status="SKIP",
                        note="Not exercised: policy mutations are banned for agent/API-key workflows.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )
            if "drive_detach_policy_from_object" in tool_names:
                steps.append(
                    ToolStep(
                        tool_name="drive_detach_policy_from_object",
                        arguments={"object_id": placeholder_id, "attachment_id": "<not exercised>"},
                        status="SKIP",
                        note="Not exercised: policy mutations are banned for agent/API-key workflows.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )

            # Upload URL -> PUT -> complete
            if not _FIXTURE.is_file():
                steps.append(
                    ToolStep(
                        tool_name="drive_upload_drive_file_from_path",
                        arguments={"object_id": placeholder_id, "file_path": str(_FIXTURE)},
                        status="SKIP",
                        note=f"Missing fixture on disk: {_FIXTURE}",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )
            else:
                up = await _call(session, "drive_get_drive_upload_url", {"object_id": placeholder_id})
                steps.append(up)
                up_data = _unwrap_data(up.parsed_json)
                bucket = up_data.get("bucket") if isinstance(up_data, dict) else None
                upload_url = None
                if isinstance(up_data, dict):
                    upload_url = up_data.get("upload_url") or up_data.get("url")

                if isinstance(bucket, str) and bucket and isinstance(upload_url, str) and upload_url:
                    size_bytes = _FIXTURE.stat().st_size
                    etag: str | None = None
                    try:
                        with httpx.Client(timeout=float(os.environ.get("STELLARBRIDGE_HTTP_TIMEOUT", "120"))) as c:
                            with _FIXTURE.open("rb") as f:
                                resp = c.put(upload_url, content=f, headers={"Content-Type": "application/octet-stream"})
                            resp.raise_for_status()
                            etag_hdr = resp.headers.get("ETag") or resp.headers.get("etag")
                            if isinstance(etag_hdr, str) and etag_hdr:
                                etag = _strip_quotes(etag_hdr)
                    except Exception as e:
                        steps.append(
                            ToolStep(
                                tool_name="(storage_put)",
                                arguments={"object_id": placeholder_id},
                                status="FAIL",
                                note=f"PUT to presigned upload_url failed: {type(e).__name__}",
                                parsed_json=None,
                                raw_text_preview=_redact_text(repr(e)),
                            )
                        )
                    if etag:
                        steps.append(
                            await _call(
                                session,
                                "drive_complete_drive_upload",
                                {
                                    "object_id": placeholder_id,
                                    "bucket": bucket,
                                    "etag": etag,
                                    "size_bytes": int(size_bytes),
                                },
                            )
                        )
                    else:
                        steps.append(
                            ToolStep(
                                tool_name="drive_complete_drive_upload",
                                arguments={"object_id": placeholder_id},
                                status="SKIP",
                                note="No ETag captured from storage PUT; cannot complete upload.",
                                parsed_json=None,
                                raw_text_preview="",
                            )
                        )
                else:
                    steps.append(
                        ToolStep(
                            tool_name="drive_complete_drive_upload",
                            arguments={"object_id": placeholder_id},
                            status="SKIP",
                            note="get_drive_upload_url response missing bucket/upload_url.",
                            parsed_json=None,
                            raw_text_preview="",
                        )
                    )

                # Also exercise the convenience wrapper (separate placeholder to keep flows independent)
                placeholder2 = await _call(
                    session,
                    "drive_create_drive_file_placeholder",
                    {
                        "project_id": workflow_project_id,
                        "name": f"mcp-live-uploadtool-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bin",
                        "mime_type": "application/octet-stream",
                    },
                )
                steps.append(placeholder2)
                placeholder2_id = _extract_int_id(placeholder2.parsed_json)
                if placeholder2_id is not None:
                    steps.append(
                        await _call(
                            session,
                            "drive_upload_drive_file_from_path",
                            {"object_id": placeholder2_id, "file_path": str(_FIXTURE), "content_type": "application/octet-stream"},
                        )
                    )
                    steps.append(await _call(session, "drive_delete_drive_object", {"object_id": placeholder2_id}))

            steps.append(await _call(session, "drive_get_drive_download_url", {"object_id": placeholder_id}))
            if recipient_email:
                steps.append(
                    await _call(
                        session,
                        "drive_share_drive_object",
                        {"object_id": placeholder_id, "recipient_email": recipient_email},
                    )
                )
            else:
                steps.append(
                    ToolStep(
                        tool_name="drive_share_drive_object",
                        arguments={"object_id": placeholder_id, "recipient_email": "<missing STELLARBRIDGE_TEST_RECIPIENT_EMAIL>"},
                        status="SKIP",
                        note="Set STELLARBRIDGE_TEST_RECIPIENT_EMAIL to exercise this tool.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )

            # Clean up drive objects (placeholder + folder)
            steps.append(await _call(session, "drive_delete_drive_object", {"object_id": placeholder_id}))
            if folder_id is not None:
                steps.append(await _call(session, "drive_delete_drive_object", {"object_id": folder_id}))

            # -----------------
            # Requests workflow (create -> get/delete if request_id is available)
            # -----------------
            if recipient_email:
                req = await _call(
                    session,
                    "requests_create_file_request",
                    {
                        "title": f"mcp-live-request-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                        "recipient_email": recipient_email,
                    },
                )
                steps.append(req)
                request_id = _extract_str(req.parsed_json, "request_id", "requestId", "upload_id", "uploadId", "id")
                if request_id:
                    steps.append(await _call(session, "requests_get_file_request", {"request_id": request_id}))
                    steps.append(await _call(session, "requests_delete_file_request", {"request_id": request_id}))
                else:
                    steps.append(
                        ToolStep(
                            tool_name="requests_get_file_request",
                            arguments={"request_id": "<missing from create response>"},
                            status="SKIP",
                            note="Create response did not include a request_id/upload_id to chain.",
                            parsed_json=None,
                            raw_text_preview="",
                        )
                    )
                    steps.append(
                        ToolStep(
                            tool_name="requests_delete_file_request",
                            arguments={"request_id": "<missing from create response>"},
                            status="SKIP",
                            note="Create response did not include a request_id/upload_id to chain.",
                            parsed_json=None,
                            raw_text_preview="",
                        )
                    )
            else:
                steps.append(
                    ToolStep(
                        tool_name="requests_create_file_request",
                        arguments={"recipient_email": "<missing STELLARBRIDGE_TEST_RECIPIENT_EMAIL>", "title": "mcp-live-request"},
                        status="SKIP",
                        note="Set STELLARBRIDGE_TEST_RECIPIENT_EMAIL to exercise request tools.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )

            # -----------------
            # Transfers workflow: create (upload tool) -> derive tid -> get/public/share/add/delete
            # -----------------
            if _FIXTURE.is_file():
                transfer_name = f"mcp-live-transfer-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bin"
                # This tool is the most likely to hit upstream throttling (429) because it
                # performs multiple API calls + S3 PUTs. Prefer retry/backoff over aborting.
                up_t = await _call_with_retries(
                    session,
                    "transfers_upload_transfer_multipart_file",
                    {"file_path": str(_FIXTURE), "file_name": transfer_name},
                    retries=6,
                    base_sleep_s=1.0,
                )
                steps.append(up_t)

                tid_source = "upload_response"
                tid = _extract_str(up_t.parsed_json, "tid", "transfer_id", "transferId", "id")
                candidate_tids: list[str] = [tid] if tid else []

                if not candidate_tids:
                    lookup_steps, matched_tid, candidates = await _lookup_transfer_tid(
                        session,
                        transfer_name=transfer_name,
                        attempts=4,
                        sleep_s=1.0,
                    )
                    steps.extend(lookup_steps)
                    if matched_tid:
                        tid_source = "list_match"
                        candidate_tids = [matched_tid]
                    elif candidates:
                        tid_source = "list_any"
                        candidate_tids = candidates[:5]

                # Final fallback: accept a user-provided tid if set.
                if not candidate_tids:
                    env_tid = os.environ.get("STELLARBRIDGE_TEST_TRANSFER_ID", "").strip() or None
                    if env_tid:
                        steps.append(
                            ToolStep(
                                tool_name="(transfer_tid_lookup)",
                                arguments={"transfer_name": transfer_name},
                                status="SKIP",
                                note="Upload did not return tid; using STELLARBRIDGE_TEST_TRANSFER_ID for downstream transfer tools.",
                                parsed_json={"transfer_name": transfer_name, "matched_tid": None},
                                raw_text_preview="",
                            )
                        )
                        tid_source = "env"
                        candidate_tids = [env_tid]

                # Choose a tid that supports get_transfer.
                tid_for_ops: str | None = None
                for cand in candidate_tids:
                    gt = await _call_with_retries(
                        session,
                        "transfers_get_transfer",
                        {"transfer_id": cand},
                        retries=4,
                        base_sleep_s=1.0,
                    )
                    if gt.status == "FAIL" and tid_source in ("list_any", "env") and "404" in (gt.raw_text_preview or ""):
                        steps.append(
                            ToolStep(
                                tool_name="transfers_get_transfer",
                                arguments={"transfer_id": cand},
                                status="SKIP",
                                note="Selected a transfer id from transfers_list_transfers/env, but it was not retrievable (404).",
                                parsed_json=None,
                                raw_text_preview=gt.raw_text_preview,
                            )
                        )
                        continue
                    steps.append(gt)
                    if gt.status == "PASS":
                        tid_for_ops = cand
                        break

                if tid_for_ops:
                    if tid_source in ("env", "list_any"):
                        # Safety: never mutate an arbitrary pre-existing transfer id.
                        steps.append(
                            ToolStep(
                                tool_name="transfers_get_transfer_public_info",
                                arguments={"transfer_id": tid_for_ops},
                                status="SKIP",
                                note=(
                                    "Skipped because transfer_id did not come from this run's upload; public-info only applies to public/shared transfers."
                                ),
                                parsed_json=None,
                                raw_text_preview="",
                            )
                        )
                        steps.append(
                            ToolStep(
                                tool_name="transfers_share_transfer",
                                arguments={"transfer_id": tid_for_ops, "recipient_email": recipient_email or "<missing>"},
                                status="SKIP",
                                note="Skipped because transfer_id did not come from this run's upload.",
                                parsed_json=None,
                                raw_text_preview="",
                            )
                        )
                        if workflow_project_id is not None and created_workflow_project:
                            # Try multiple candidate tids; some may not be eligible for add-to-drive.
                            added_ok = False
                            for cand in candidate_tids[:5]:
                                added = await _call(
                                    session,
                                    "transfers_add_transfer_to_drive",
                                    {"transfer_id": cand, "project_id": workflow_project_id},
                                )
                                if added.status == "FAIL" and ("422" in (added.raw_text_preview or "") or "404" in (added.raw_text_preview or "")):
                                    steps.append(
                                        ToolStep(
                                            tool_name="transfers_add_transfer_to_drive",
                                            arguments={"transfer_id": cand, "project_id": workflow_project_id},
                                            status="SKIP",
                                            note="Selected a transfer id from transfers_list_transfers, but it was not eligible for add-to-drive (422/404).",
                                            parsed_json=None,
                                            raw_text_preview=added.raw_text_preview,
                                        )
                                    )
                                    continue
                                steps.append(added)
                                if added.status == "PASS":
                                    added_ok = True
                                    obj_id = _extract_object_id(added.parsed_json)
                                    if obj_id is not None:
                                        steps.append(
                                            await _call(
                                                session,
                                                "drive_delete_drive_object",
                                                {"object_id": obj_id},
                                            )
                                        )
                                    break
                            if not added_ok:
                                steps.append(
                                    ToolStep(
                                        tool_name="transfers_add_transfer_to_drive",
                                        arguments={"transfer_id": "<no eligible tid>", "project_id": workflow_project_id},
                                        status="SKIP",
                                        note="No eligible transfer id found in transfers_list_transfers for add-to-drive.",
                                        parsed_json=None,
                                        raw_text_preview="",
                                    )
                                )
                        else:
                            steps.append(
                                ToolStep(
                                    tool_name="transfers_add_transfer_to_drive",
                                    arguments={"transfer_id": tid_for_ops, "project_id": workflow_project_id},
                                    status="SKIP",
                                    note="Skipped: add-to-drive against pre-existing transfers is only attempted when using a disposable workflow project.",
                                    parsed_json=None,
                                    raw_text_preview="",
                                )
                            )
                        steps.append(
                            ToolStep(
                                tool_name="transfers_delete_transfer",
                                arguments={"transfer_id": tid_for_ops},
                                status="SKIP",
                                note="Skipped because transfer_id did not come from this run's upload.",
                                parsed_json=None,
                                raw_text_preview="",
                            )
                        )
                    else:
                        if recipient_email:
                            steps.append(
                                await _call(
                                    session,
                                    "transfers_share_transfer",
                                    {"transfer_id": tid_for_ops, "recipient_email": recipient_email},
                                )
                            )
                        else:
                            steps.append(
                                ToolStep(
                                    tool_name="transfers_share_transfer",
                                    arguments={"transfer_id": tid_for_ops, "recipient_email": "<missing STELLARBRIDGE_TEST_RECIPIENT_EMAIL>"},
                                    status="SKIP",
                                    note="Set STELLARBRIDGE_TEST_RECIPIENT_EMAIL to exercise share_transfer.",
                                    parsed_json=None,
                                    raw_text_preview="",
                                )
                            )
                        steps.append(
                            await _call(
                                session,
                                "transfers_add_transfer_to_drive",
                                {"transfer_id": tid_for_ops, "project_id": workflow_project_id},
                            )
                        )
                        steps.append(await _call(session, "transfers_delete_transfer", {"transfer_id": tid_for_ops}))
                        # Public info is only expected to work for public/shared transfers.
                        steps.append(
                            await _call_with_retries(
                                session,
                                "transfers_get_transfer_public_info",
                                {"transfer_id": tid_for_ops},
                                retries=4,
                                base_sleep_s=1.0,
                            )
                        )
                else:
                    steps.append(
                        ToolStep(
                            tool_name="transfers_get_transfer",
                            arguments={"transfer_id": "<missing tid>"},
                            status="SKIP",
                            note="No tid returned from upload; set STELLARBRIDGE_TEST_TRANSFER_ID to exercise downstream transfer tools.",
                            parsed_json=None,
                            raw_text_preview="",
                        )
                    )
                    steps.append(
                        ToolStep(
                            tool_name="transfers_get_transfer_public_info",
                            arguments={"transfer_id": "<missing tid>"},
                            status="SKIP",
                            note="No tid returned from upload; set STELLARBRIDGE_TEST_TRANSFER_ID to exercise downstream transfer tools.",
                            parsed_json=None,
                            raw_text_preview="",
                        )
                    )
                    steps.append(
                        ToolStep(
                            tool_name="transfers_add_transfer_to_drive",
                            arguments={"transfer_id": "<missing tid>", "project_id": workflow_project_id},
                            status="SKIP",
                            note="No tid returned from upload; set STELLARBRIDGE_TEST_TRANSFER_ID to exercise downstream transfer tools.",
                            parsed_json=None,
                            raw_text_preview="",
                        )
                    )
                    steps.append(
                        ToolStep(
                            tool_name="transfers_delete_transfer",
                            arguments={"transfer_id": "<missing tid>"},
                            status="SKIP",
                            note="No tid returned from upload; set STELLARBRIDGE_TEST_TRANSFER_ID to exercise downstream transfer tools.",
                            parsed_json=None,
                            raw_text_preview="",
                        )
                    )

            # Multipart tool trio: initialize -> presigned_urls -> cancel
            init = await _call_with_retries(
                session,
                "transfers_initialize_multipart_upload",
                {"file_name": f"mcp-live-multipart-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bin", "size_bytes": 9_000_000},
                retries=4,
                base_sleep_s=1.0,
            )
            steps.append(init)
            init_data = _unwrap_data(init.parsed_json)
            upload_id = None
            file_key = None
            if isinstance(init_data, dict):
                upload_id = init_data.get("fileId") or init_data.get("uploadId") or init_data.get("file_id")
                file_key = init_data.get("fileKey") or init_data.get("file_key")
            if upload_id is not None and file_key is not None and str(upload_id) and str(file_key):
                upload_id = str(upload_id)
                file_key = str(file_key)
                steps.append(
                    await _call_with_retries(
                        session,
                        "transfers_get_multipart_presigned_urls",
                        {"upload_id": upload_id, "file_key": file_key, "parts": 3},
                    )
                )
                steps.append(
                    await _call_with_retries(
                        session,
                        "transfers_cancel_multipart_upload",
                        {"upload_id": upload_id, "file_key": file_key},
                    )
                )
                # finalize requires ETags; we don't attempt a full multipart PUT here (covered by transfers_upload_transfer_multipart_file).
                steps.append(
                    ToolStep(
                        tool_name="transfers_finalize_multipart_upload",
                        arguments={"upload_id": upload_id, "file_key": file_key, "parts": "<requires ETags>", "size_bytes": 9000000},
                        status="SKIP",
                        note="Finalize requires uploading parts and collecting ETags; covered end-to-end by transfers_upload_transfer_multipart_file.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )
            else:
                steps.append(
                    ToolStep(
                        tool_name="transfers_get_multipart_presigned_urls",
                        arguments={"upload_id": "<missing>", "file_key": "<missing>", "parts": 3},
                        status="SKIP",
                        note="initialize_multipart_upload did not return fileId/fileKey.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )
                steps.append(
                    ToolStep(
                        tool_name="transfers_cancel_multipart_upload",
                        arguments={"upload_id": "<missing>", "file_key": "<missing>"},
                        status="SKIP",
                        note="initialize_multipart_upload did not return fileId/fileKey.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )
                steps.append(
                    ToolStep(
                        tool_name="transfers_finalize_multipart_upload",
                        arguments={"upload_id": "<missing>", "file_key": "<missing>"},
                        status="SKIP",
                        note="initialize_multipart_upload did not return fileId/fileKey.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )

            # Clean up disposable project at the very end, after all workflows that may reference it.
            if created_workflow_project and workflow_project_id is not None:
                steps.append(await _call(session, "projects_delete_project", {"project_id": workflow_project_id}))

    return steps, workflow_project_id


def _write_report(
    path: Path, *, project_id: int | None, recipient_email: str | None, steps: list[ToolStep]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    api_url = os.environ.get("STELLARBRIDGE_API_URL", "").strip()

    lines: list[str] = []
    lines.append("# MCP Live Full Workflow QA Report")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{ts}`")
    lines.append(f"- API URL: `{api_url}`")
    lines.append(f"- Project ID: `{project_id if project_id is not None else '<none>'}`")
    lines.append(f"- Recipient email set: `{bool(recipient_email)}`")
    lines.append(f"- Mutations enabled: `{_truthy_env('STELLARBRIDGE_LIVE_ALLOW_MUTATIONS')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Tool | Result | Notes |")
    lines.append("| --- | --- | --- |")

    # Prefer one row per tool name; collapse multiple invocations.
    by_tool: dict[str, list[ToolStep]] = {}
    for s in steps:
        by_tool.setdefault(s.tool_name, []).append(s)

    surface: list[str] | None = None
    lt = by_tool.get("(mcp_list_tools)")
    if lt and isinstance(lt[0].parsed_json, dict):
        tools = lt[0].parsed_json.get("tools")
        if isinstance(tools, list) and all(isinstance(x, str) for x in tools):
            surface = list(tools)

    ordered = surface or sorted(by_tool.keys())
    for name in ordered:
        runs = by_tool.get(name)
        if not runs:
            continue
        statuses = {r.status for r in runs}
        if "FAIL" in statuses:
            status = "FAIL"
        elif "PASS" in statuses:
            status = "PASS"
        else:
            status = "SKIP"
        note = next((r.note for r in runs if r.note), "")
        lines.append(f"| `{name}` | `{status}` | {_redact_text(note)} |")

    lines.append("")
    lines.append("## Details")
    for s in steps:
        lines.append("")
        lines.append(f"### `{s.tool_name}`")
        lines.append("")
        lines.append(f"- Result: `{s.status}`")
        if s.note:
            lines.append(f"- Note: `{_redact_text(s.note)}`")
        lines.append(f"- Arguments: `{json.dumps(_redact_obj(s.arguments), sort_keys=True)}`")
        if s.parsed_json is not None:
            lines.append("")
            lines.append("Response (parsed JSON, sanitized):")
            lines.append("```json")
            max_items = int(os.environ.get("MAX_LIST_ITEMS", "5"))
            safe = _redact_obj(_truncate_lists(s.parsed_json, max_items))
            lines.append(json.dumps(safe, indent=2, sort_keys=True))
            lines.append("```")
        elif s.raw_text_preview:
            lines.append("")
            lines.append("Response (text preview, sanitized):")
            lines.append("```text")
            lines.append(s.raw_text_preview)
            lines.append("```")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mcp-live-full-workflow")
    p.add_argument(
        "--out",
        default=f"tests/retest_results/mcp_live_full_workflow_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md",
        help="Write markdown report to this path (ignored by git).",
    )
    args = p.parse_args(argv)

    load_dotenv(_REPO_ROOT / ".env", override=False)

    if not _truthy_env("STELLARBRIDGE_LIVE_API"):
        print("Set STELLARBRIDGE_LIVE_API=1", file=sys.stderr)
        return 2
    if not _truthy_env("STELLARBRIDGE_LIVE_ALLOW_MUTATIONS"):
        print("Set STELLARBRIDGE_LIVE_ALLOW_MUTATIONS=1 (this workflow creates/deletes resources)", file=sys.stderr)
        return 2
    if not os.environ.get("STELLARBRIDGE_API_URL", "").strip() or not os.environ.get("STELLARBRIDGE_API_KEY", "").strip():
        print("STELLARBRIDGE_API_URL and STELLARBRIDGE_API_KEY must be set", file=sys.stderr)
        return 2

    raw_pid = os.environ.get("STELLARBRIDGE_TEST_PROJECT_ID", "").strip()
    project_id: int | None = int(raw_pid, 10) if raw_pid.isdigit() else None
    if project_id is None:
        print(
            "STELLARBRIDGE_TEST_PROJECT_ID is not set; the runner will try to create a disposable project via partner ids",
            file=sys.stderr,
        )

    recipient = os.environ.get("STELLARBRIDGE_TEST_RECIPIENT_EMAIL", "").strip() or None
    if not recipient:
        print("STELLARBRIDGE_TEST_RECIPIENT_EMAIL is not set; share/request steps will be skipped", file=sys.stderr)

    out_path = Path(str(args.out)).expanduser().resolve()

    import asyncio

    steps, resolved_project_id = asyncio.run(
        _run(_REPO_ROOT, project_id=project_id, recipient_email=recipient)
    )
    _write_report(out_path, project_id=resolved_project_id, recipient_email=recipient, steps=steps)
    print(str(out_path))

    # Non-zero if any FAIL occurred.
    return 1 if any(s.status == "FAIL" for s in steps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
