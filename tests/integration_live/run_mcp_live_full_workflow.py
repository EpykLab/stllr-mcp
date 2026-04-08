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


def _first_text_block(content: list[Any]) -> str | None:
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
        if it.get("name") != name:
            continue
        tid = it.get("tid") or it.get("id") or it.get("transfer_id")
        if isinstance(tid, str) and tid:
            return tid
    return None


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
    return ToolStep(
        tool_name=tool_name,
        arguments=arguments,
        status="PASS" if ok else "FAIL",
        note="",
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


async def _run(repo_root: Path, *, project_id: int, recipient_email: str | None) -> list[ToolStep]:
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
            steps.append(await _call(session, "projects_list_projects", {}))
            steps.append(await _call(session, "audit_get_audit_logs", {}))
            steps.append(
                await _call(session, "audit_get_audit_logs_for_file", {"file_name": "mcp-live-workflow"})
            )
            if os.environ.get("STELLARBRIDGE_TEST_ACTOR_ID"):
                steps.append(
                    await _call(
                        session,
                        "audit_get_audit_logs_for_actor",
                        {"actor_id": os.environ["STELLARBRIDGE_TEST_ACTOR_ID"]},
                    )
                )
            else:
                steps.append(
                    ToolStep(
                        tool_name="audit_get_audit_logs_for_actor",
                        arguments={"actor_id": "<missing STELLARBRIDGE_TEST_ACTOR_ID>"},
                        status="SKIP",
                        note="Set STELLARBRIDGE_TEST_ACTOR_ID to exercise this tool.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )

            steps.append(await _call(session, "drive_list_drive_objects", {"project_id": project_id}))

            # -----------------
            # Drive workflow: folder + placeholder + rename + move + upload-url + PUT + complete + download-url + share + delete
            # -----------------
            folder = await _call(
                session,
                "drive_create_drive_folder",
                {"project_id": project_id, "name": f"mcp-live-folder-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"},
            )
            steps.append(folder)
            folder_id = _extract_int_id(folder.parsed_json)

            placeholder = await _call(
                session,
                "drive_create_drive_file_placeholder",
                {
                    "project_id": project_id,
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

            # Optional policy attach/detach (often blocked for ApiAgent keys)
            policy_id = os.environ.get("STELLARBRIDGE_TEST_POLICY_ID", "").strip()
            attachment_id = os.environ.get("STELLARBRIDGE_TEST_ATTACHMENT_ID", "").strip()
            if policy_id.isdigit():
                steps.append(
                    await _call(
                        session,
                        "drive_attach_policy_to_object",
                        {"object_id": placeholder_id, "policy_id": int(policy_id, 10)},
                    )
                )
            else:
                steps.append(
                    ToolStep(
                        tool_name="drive_attach_policy_to_object",
                        arguments={"object_id": placeholder_id, "policy_id": "<missing STELLARBRIDGE_TEST_POLICY_ID>"},
                        status="SKIP",
                        note="Set STELLARBRIDGE_TEST_POLICY_ID to exercise this tool.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )

            if attachment_id:
                steps.append(
                    await _call(
                        session,
                        "drive_detach_policy_from_object",
                        {"object_id": placeholder_id, "attachment_id": attachment_id},
                    )
                )
            else:
                steps.append(
                    ToolStep(
                        tool_name="drive_detach_policy_from_object",
                        arguments={"object_id": placeholder_id, "attachment_id": "<missing STELLARBRIDGE_TEST_ATTACHMENT_ID>"},
                        status="SKIP",
                        note="Set STELLARBRIDGE_TEST_ATTACHMENT_ID to exercise this tool.",
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
                        "project_id": project_id,
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
                up_t = await _call(
                    session,
                    "transfers_upload_transfer_multipart_file",
                    {"file_path": str(_FIXTURE), "file_name": transfer_name},
                )
                steps.append(up_t)

                # Prefer returned tid if API now provides it.
                tid = _extract_str(up_t.parsed_json, "tid", "transfer_id", "transferId", "id")

                if not tid:
                    # Fallback: discover tid by listing transfers and matching on generated name.
                    # Keep this intentionally lightweight to avoid rate limiting.
                    lt = await _call_with_retries(session, "transfers_list_transfers", {}, retries=4, base_sleep_s=1.0)
                    steps.append(lt)
                    tid = _find_transfer_tid_by_name(lt.parsed_json, name=transfer_name) if lt.status == "PASS" else None

                    steps.append(
                        ToolStep(
                            tool_name="(transfer_tid_lookup)",
                            arguments={"transfer_name": transfer_name},
                            status="PASS" if tid else "FAIL",
                            note="matched by name via transfers_list_transfers" if tid else "no matching tid found in transfers_list_transfers",
                            parsed_json={"transfer_name": transfer_name, "matched_tid": tid},
                            raw_text_preview="",
                        )
                    )

                if not tid:
                    # Final fallback: accept a user-provided tid if set.
                    tid = os.environ.get("STELLARBRIDGE_TEST_TRANSFER_ID", "").strip() or None

                if tid:
                    steps.append(await _call(session, "transfers_get_transfer", {"transfer_id": tid}))
                    steps.append(
                        await _call(session, "transfers_get_transfer_public_info", {"transfer_id": tid})
                    )
                    if recipient_email:
                        steps.append(
                            await _call(
                                session,
                                "transfers_share_transfer",
                                {"transfer_id": tid, "recipient_email": recipient_email},
                            )
                        )
                    else:
                        steps.append(
                            ToolStep(
                                tool_name="transfers_share_transfer",
                                arguments={"transfer_id": tid, "recipient_email": "<missing STELLARBRIDGE_TEST_RECIPIENT_EMAIL>"},
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
                            {"transfer_id": tid, "project_id": project_id},
                        )
                    )
                    steps.append(await _call(session, "transfers_delete_transfer", {"transfer_id": tid}))
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
                            arguments={"transfer_id": "<missing tid>", "project_id": project_id},
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
            init = await _call(
                session,
                "transfers_initialize_multipart_upload",
                {"file_name": f"mcp-live-multipart-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bin", "size_bytes": 9_000_000},
            )
            steps.append(init)
            init_data = _unwrap_data(init.parsed_json)
            upload_id = init_data.get("fileId") if isinstance(init_data, dict) else None
            file_key = init_data.get("fileKey") if isinstance(init_data, dict) else None
            if isinstance(upload_id, str) and isinstance(file_key, str) and upload_id and file_key:
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

            # Projects create/delete require partner IDs.
            if os.environ.get("STELLARBRIDGE_TEST_PARTNER_IDS", "").strip():
                # Leave to the parametrized live pytest suite for now.
                steps.append(
                    ToolStep(
                        tool_name="projects_create_project",
                        arguments={"name": "<auto>", "partner_ids": "<from STELLARBRIDGE_TEST_PARTNER_IDS>"},
                        status="SKIP",
                        note="Not implemented in workflow runner yet (prefer live pytest spec with partner IDs).",
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
                        note="Set STELLARBRIDGE_TEST_PARTNER_IDS to exercise projects_create_project.",
                        parsed_json=None,
                        raw_text_preview="",
                    )
                )
            steps.append(
                ToolStep(
                    tool_name="projects_delete_project",
                    arguments={"project_id": "<requires empty disposable project>"},
                    status="SKIP",
                    note="Requires an empty disposable project id (or implement project create+cleanup).",
                    parsed_json=None,
                    raw_text_preview="",
                )
            )

    return steps


def _write_report(path: Path, *, project_id: int, recipient_email: str | None, steps: list[ToolStep]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    api_url = os.environ.get("STELLARBRIDGE_API_URL", "").strip()

    lines: list[str] = []
    lines.append("# MCP Live Full Workflow QA Report")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{ts}`")
    lines.append(f"- API URL: `{api_url}`")
    lines.append(f"- Project ID: `{project_id}`")
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
    if not raw_pid.isdigit():
        print("Set STELLARBRIDGE_TEST_PROJECT_ID (numeric Drive project id)", file=sys.stderr)
        return 2
    project_id = int(raw_pid, 10)

    recipient = os.environ.get("STELLARBRIDGE_TEST_RECIPIENT_EMAIL", "").strip() or None
    if not recipient:
        print("STELLARBRIDGE_TEST_RECIPIENT_EMAIL is not set; share/request steps will be skipped", file=sys.stderr)

    out_path = Path(str(args.out)).expanduser().resolve()

    import asyncio

    steps = asyncio.run(_run(_REPO_ROOT, project_id=project_id, recipient_email=recipient))
    _write_report(out_path, project_id=project_id, recipient_email=recipient, steps=steps)
    print(str(out_path))

    # Non-zero if any FAIL occurred.
    return 1 if any(s.status == "FAIL" for s in steps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
