"""Per-tool argument resolution for live MCP tests (real API, opt-in).

Each tool maps to env-driven arguments. ``resolve`` returns ``(args, skip_reason)``;
``args is None`` means the test should be skipped (missing env or mutation guard).

Mutation-prone tools require ``STELLARBRIDGE_LIVE_ALLOW_MUTATIONS=1`` in addition to
any resource IDs. Destructive calls use IDs from the environment only; the operator
is responsible for pointing them at disposable resources.

When a **transfer id** (``tid``) is required and not in env: call MCP tool
``transfers_list_transfers`` first; each row includes ``tid``. Do not use raw HTTP
to list transfers for that purpose. See README "Transfer ids" and ``tests/README.md``.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any, Final

from tests.integration.mcp_tool_cases import EXPECTED_MCP_TOOL_NAMES

# Committed multipart fixture (same as mock integration tests).
_MULTIPART_FIXTURE_RELATIVE: Final = Path("tests/fixtures/uploads/multipart_upload.bin")


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


# Shown when live tests skip for missing STELLARBRIDGE_TEST_TRANSFER_ID (etc.).
_TRANSFER_TID_HINT = (
    "Call MCP tool transfers_list_transfers and use a row's tid, or "
    "`task live-first-transfer-id` / tests/README.md."
)

# Create response omits upload/request id for requesters (EPY-186); see stllr#408.
_REQUEST_ID_HINT = (
    "Until the API returns an id on create, set STELLARBRIDGE_TEST_REQUEST_ID to "
    "the UUID from the recipient invite email (…/public/upload/{uuid}) or another "
    "supported source."
)


def _env_str(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v or None


def _env_int(name: str) -> int | None:
    raw = _env_str(name)
    if raw is None:
        return None
    try:
        return int(raw, 10)
    except ValueError:
        return None


def _require_mutation_allow() -> str | None:
    if not _truthy_env("STELLARBRIDGE_LIVE_ALLOW_MUTATIONS"):
        return "Set STELLARBRIDGE_LIVE_ALLOW_MUTATIONS=1 to run mutation/destructive tools."
    return None


def _partner_ids() -> list[int] | None:
    raw = _env_str("STELLARBRIDGE_TEST_PARTNER_IDS")
    if not raw:
        return None
    out: list[int] = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        out.append(int(p, 10))
    return out or None


@dataclass(frozen=True)
class LiveToolSpec:
    tool_name: str
    resolve: Callable[[Path], tuple[dict[str, Any] | None, str]]

    def __call__(self, repo_root: Path) -> tuple[dict[str, Any] | None, str]:
        return self.resolve(repo_root)


def _audit_get_audit_logs(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    return {}, ""


def _audit_get_audit_logs_for_actor(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    aid = _env_str("STELLARBRIDGE_TEST_ACTOR_ID")
    if not aid:
        return None, "Set STELLARBRIDGE_TEST_ACTOR_ID for this tool."
    return {"actor_id": aid}, ""


def _audit_get_audit_logs_for_file(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    name = _env_str("STELLARBRIDGE_TEST_AUDIT_FILE_NAME")
    if not name:
        name = "live-mcp-audit-contract.txt"
    return {"file_name": name}, ""


def _drive_list_drive_objects(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    pid = _env_int("STELLARBRIDGE_TEST_PROJECT_ID")
    if pid is None:
        return None, "Set STELLARBRIDGE_TEST_PROJECT_ID for this tool."
    return {"project_id": pid}, ""


def _drive_get_drive_object(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    oid = _env_int("STELLARBRIDGE_TEST_OBJECT_ID")
    if oid is None:
        return None, "Set STELLARBRIDGE_TEST_OBJECT_ID for this tool."
    return {"object_id": oid}, ""


def _drive_create_drive_folder(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    pid = _env_int("STELLARBRIDGE_TEST_PROJECT_ID")
    if pid is None:
        return None, "Set STELLARBRIDGE_TEST_PROJECT_ID for this tool."
    name = f"live-mcp-folder-{uuid.uuid4().hex[:12]}"
    return {"project_id": pid, "name": name}, ""


def _drive_create_drive_file_placeholder(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    pid = _env_int("STELLARBRIDGE_TEST_PROJECT_ID")
    if pid is None:
        return None, "Set STELLARBRIDGE_TEST_PROJECT_ID for this tool."
    fname = f"live-placeholder-{uuid.uuid4().hex[:12]}.pdf"
    return {"project_id": pid, "name": fname, "mime_type": "application/pdf"}, ""


def _drive_rename_drive_object(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    oid = _env_int("STELLARBRIDGE_TEST_OBJECT_ID")
    if oid is None:
        return None, "Set STELLARBRIDGE_TEST_OBJECT_ID for this tool."
    new_name = f"live-renamed-{uuid.uuid4().hex[:12]}.txt"
    return {"object_id": oid, "new_name": new_name}, ""


def _drive_move_drive_object(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    oid = _env_int("STELLARBRIDGE_TEST_OBJECT_ID")
    if oid is None:
        return None, "Set STELLARBRIDGE_TEST_OBJECT_ID for this tool."
    parent = _env_int("STELLARBRIDGE_TEST_MOVE_PARENT_OBJECT_ID")
    if parent is not None:
        return {"object_id": oid, "new_parent_id": parent}, ""
    return {"object_id": oid}, ""


def _drive_delete_drive_object(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    oid = _env_int("STELLARBRIDGE_TEST_DELETE_OBJECT_ID")
    if oid is None:
        return (
            None,
            "Set STELLARBRIDGE_TEST_DELETE_OBJECT_ID (disposable object) for this tool.",
        )
    return {"object_id": oid}, ""


def _drive_get_drive_upload_url(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    oid = _env_int("STELLARBRIDGE_TEST_FILE_PLACEHOLDER_OBJECT_ID")
    if oid is None:
        oid = _env_int("STELLARBRIDGE_TEST_OBJECT_ID")
    if oid is None:
        return (
            None,
            "Set STELLARBRIDGE_TEST_FILE_PLACEHOLDER_OBJECT_ID or "
            "STELLARBRIDGE_TEST_OBJECT_ID (file placeholder).",
        )
    return {"object_id": oid}, ""


def _drive_upload_drive_file_from_path(repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    oid = _env_int("STELLARBRIDGE_TEST_FILE_PLACEHOLDER_OBJECT_ID")
    if oid is None:
        oid = _env_int("STELLARBRIDGE_TEST_OBJECT_ID")
    if oid is None:
        return (
            None,
            "Set STELLARBRIDGE_TEST_FILE_PLACEHOLDER_OBJECT_ID or "
            "STELLARBRIDGE_TEST_OBJECT_ID (file placeholder).",
        )
    fixture = (repo_root / _MULTIPART_FIXTURE_RELATIVE).resolve()
    if not fixture.is_file():
        return None, f"missing committed fixture: {fixture}"
    return {
        "object_id": oid,
        "file_path": str(fixture),
        "content_type": "application/octet-stream",
    }, ""


def _drive_complete_drive_upload(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    oid = _env_int("STELLARBRIDGE_TEST_FILE_PLACEHOLDER_OBJECT_ID")
    if oid is None:
        oid = _env_int("STELLARBRIDGE_TEST_OBJECT_ID")
    if oid is None:
        return (
            None,
            "Set STELLARBRIDGE_TEST_FILE_PLACEHOLDER_OBJECT_ID or "
            "STELLARBRIDGE_TEST_OBJECT_ID for this tool.",
        )
    bucket = _env_str("STELLARBRIDGE_TEST_UPLOAD_BUCKET")
    etag = _env_str("STELLARBRIDGE_TEST_UPLOAD_ETAG")
    size = _env_int("STELLARBRIDGE_TEST_UPLOAD_SIZE_BYTES")
    if not bucket or not etag or size is None or size <= 0:
        return (
            None,
            "After PUT to the presigned URL, set STELLARBRIDGE_TEST_UPLOAD_BUCKET, "
            "STELLARBRIDGE_TEST_UPLOAD_ETAG (strip surrounding quotes), and "
            "STELLARBRIDGE_TEST_UPLOAD_SIZE_BYTES for complete_drive_upload.",
        )
    return {
        "object_id": oid,
        "bucket": bucket,
        "etag": etag,
        "size_bytes": size,
    }, ""


def _drive_get_drive_download_url(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    oid = _env_int("STELLARBRIDGE_TEST_DOWNLOAD_OBJECT_ID")
    if oid is None:
        oid = _env_int("STELLARBRIDGE_TEST_OBJECT_ID")
    if oid is None:
        return (
            None,
            "Set STELLARBRIDGE_TEST_DOWNLOAD_OBJECT_ID or STELLARBRIDGE_TEST_OBJECT_ID.",
        )
    return {"object_id": oid}, ""


def _drive_share_drive_object(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    # Live API returns 422 for X-API-Key callers (documented MCP limitation).
    # Opt in when the API supports key-based share: STELLARBRIDGE_LIVE_ALLOW_DRIVE_SHARE=1
    if not _truthy_env("STELLARBRIDGE_LIVE_ALLOW_DRIVE_SHARE"):
        return None, (
            "POST /objects/:id/share is not supported for API key callers on live API (422). "
            "Set STELLARBRIDGE_LIVE_ALLOW_DRIVE_SHARE=1 when the API supports key-based share. "
            "See test_tracking.md drive_share_drive_object."
        )
    oid = _env_int("STELLARBRIDGE_TEST_OBJECT_ID")
    if oid is None:
        return None, "Set STELLARBRIDGE_TEST_OBJECT_ID for this tool."
    email = _env_str("STELLARBRIDGE_TEST_RECIPIENT_EMAIL")
    if not email:
        return None, "Set STELLARBRIDGE_TEST_RECIPIENT_EMAIL for this tool."
    return {"object_id": oid, "recipient_email": email}, ""


def _drive_list_object_policy_attachments(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    oid = _env_int("STELLARBRIDGE_TEST_OBJECT_ID")
    if oid is None:
        return None, "Set STELLARBRIDGE_TEST_OBJECT_ID for this tool."
    return {"object_id": oid}, ""


def _transfers_list_transfers(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    org = _env_str("STELLARBRIDGE_TEST_ORG_ID")
    if org:
        return {"org_id": org}, ""
    return {}, ""


def _transfers_get_transfer(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    tid = _env_str("STELLARBRIDGE_TEST_TRANSFER_ID")
    if not tid:
        return (
            None,
            f"Set STELLARBRIDGE_TEST_TRANSFER_ID (uuid). {_TRANSFER_TID_HINT}",
        )
    return {"transfer_id": tid}, ""


def _transfers_delete_transfer(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    tid = _env_str("STELLARBRIDGE_TEST_DELETE_TRANSFER_ID")
    if not tid:
        return (
            None,
            "Set STELLARBRIDGE_TEST_DELETE_TRANSFER_ID (disposable transfer) for this tool.",
        )
    return {"transfer_id": tid}, ""


def _transfers_share_transfer(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    tid = _env_str("STELLARBRIDGE_TEST_TRANSFER_ID")
    email = _env_str("STELLARBRIDGE_TEST_RECIPIENT_EMAIL")
    if not tid or not email:
        return (
            None,
            "Set STELLARBRIDGE_TEST_TRANSFER_ID and STELLARBRIDGE_TEST_RECIPIENT_EMAIL. "
            f"If tid is unknown: {_TRANSFER_TID_HINT}",
        )
    return {"transfer_id": tid, "recipient_email": email}, ""


def _transfers_add_transfer_to_drive(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    tid = _env_str("STELLARBRIDGE_TEST_TRANSFER_ID")
    pid = _env_int("STELLARBRIDGE_TEST_PROJECT_ID")
    if not tid or pid is None:
        return (
            None,
            "Set STELLARBRIDGE_TEST_TRANSFER_ID and STELLARBRIDGE_TEST_PROJECT_ID. "
            f"If tid is unknown: {_TRANSFER_TID_HINT}",
        )
    return {"transfer_id": tid, "project_id": pid}, ""


def _transfers_get_transfer_public_info(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    tid = _env_str("STELLARBRIDGE_TEST_PUBLIC_TRANSFER_ID")
    if not tid:
        tid = _env_str("STELLARBRIDGE_TEST_TRANSFER_ID")
    if not tid:
        return (
            None,
            "Set STELLARBRIDGE_TEST_PUBLIC_TRANSFER_ID or STELLARBRIDGE_TEST_TRANSFER_ID. "
            f"If tid is unknown: {_TRANSFER_TID_HINT}",
        )
    return {"transfer_id": tid}, ""


def _transfers_initialize_multipart_upload(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    return {"file_name": f"live-mcp-{uuid.uuid4().hex[:12]}.bin", "size_bytes": 9_000_000}, ""


def _transfers_get_multipart_presigned_urls(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    uid = _env_str("STELLARBRIDGE_TEST_MULTIPART_UPLOAD_ID")
    fk = _env_str("STELLARBRIDGE_TEST_MULTIPART_FILE_KEY")
    if not uid or not fk:
        return (
            None,
            "Set STELLARBRIDGE_TEST_MULTIPART_UPLOAD_ID and STELLARBRIDGE_TEST_MULTIPART_FILE_KEY "
            "(e.g. from a prior initialize_multipart_upload).",
        )
    return {"upload_id": uid, "file_key": fk, "parts": 3}, ""


def _transfers_finalize_multipart_upload(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    uid = _env_str("STELLARBRIDGE_TEST_MULTIPART_UPLOAD_ID")
    fk = _env_str("STELLARBRIDGE_TEST_MULTIPART_FILE_KEY")
    raw = _env_str("STELLARBRIDGE_TEST_MULTIPART_FINALIZE_PARTS_JSON")
    size = _env_int("STELLARBRIDGE_TEST_MULTIPART_SIZE_BYTES")
    if not uid or not fk or not raw or size is None:
        return (
            None,
            "Set STELLARBRIDGE_TEST_MULTIPART_UPLOAD_ID, STELLARBRIDGE_TEST_MULTIPART_FILE_KEY, "
            "STELLARBRIDGE_TEST_MULTIPART_SIZE_BYTES, and "
            "STELLARBRIDGE_TEST_MULTIPART_FINALIZE_PARTS_JSON (JSON array of "
            '{ "PartNumber": int, "ETag": str }).',
        )
    try:
        parts = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"Invalid STELLARBRIDGE_TEST_MULTIPART_FINALIZE_PARTS_JSON: {e}"
    if not isinstance(parts, list):
        return None, "STELLARBRIDGE_TEST_MULTIPART_FINALIZE_PARTS_JSON must be a JSON array."
    return {"upload_id": uid, "file_key": fk, "parts": parts, "size_bytes": size}, ""


def _transfers_cancel_multipart_upload(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    uid = _env_str("STELLARBRIDGE_TEST_MULTIPART_UPLOAD_ID")
    fk = _env_str("STELLARBRIDGE_TEST_MULTIPART_FILE_KEY")
    if not uid or not fk:
        return (
            None,
            "Set STELLARBRIDGE_TEST_MULTIPART_UPLOAD_ID and STELLARBRIDGE_TEST_MULTIPART_FILE_KEY.",
        )
    return {"upload_id": uid, "file_key": fk}, ""


def _transfers_upload_transfer_multipart_file(repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    override = _env_str("STELLARBRIDGE_LIVE_MULTIPART_FILE_PATH")
    if override:
        p = Path(override).expanduser().resolve()
    else:
        p = (repo_root / _MULTIPART_FIXTURE_RELATIVE).resolve()
    if not p.is_file():
        return (
            None,
            f"Multipart fixture missing: {p} (or set STELLARBRIDGE_LIVE_MULTIPART_FILE_PATH).",
        )
    return {"file_path": str(p)}, ""


def _requests_create_file_request(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    email = _env_str("STELLARBRIDGE_TEST_RECIPIENT_EMAIL")
    if not email:
        return None, "Set STELLARBRIDGE_TEST_RECIPIENT_EMAIL for this tool."
    title = f"live-mcp-request-{uuid.uuid4().hex[:12]}"
    args: dict[str, Any] = {"title": title, "recipient_email": email}
    pid = _env_int("STELLARBRIDGE_TEST_PROJECT_ID")
    if pid is not None:
        args["project_id"] = pid
    return args, ""


def _requests_get_file_request(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    rid = _env_str("STELLARBRIDGE_TEST_REQUEST_ID")
    if not rid:
        return None, f"Set STELLARBRIDGE_TEST_REQUEST_ID for this tool. {_REQUEST_ID_HINT}"
    return {"request_id": rid}, ""


def _requests_delete_file_request(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    rid = _env_str("STELLARBRIDGE_TEST_DELETE_REQUEST_ID")
    if not rid:
        return (
            None,
            "Set STELLARBRIDGE_TEST_DELETE_REQUEST_ID (disposable request) for this tool.",
        )
    return {"request_id": rid}, ""


def _projects_list_projects(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    return {}, ""


def _projects_create_project(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    partners = _partner_ids()
    if not partners:
        return None, "Set STELLARBRIDGE_TEST_PARTNER_IDS (comma-separated ints) for this tool."
    name = f"live-mcp-project-{uuid.uuid4().hex[:12]}"
    return {"name": name, "partner_ids": partners}, ""


def _projects_delete_project(_repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    r = _require_mutation_allow()
    if r is not None:
        return None, r
    pid = _env_int("STELLARBRIDGE_TEST_DELETE_PROJECT_ID")
    if pid is None:
        return (
            None,
            "Set STELLARBRIDGE_TEST_DELETE_PROJECT_ID (empty disposable project) for this tool.",
        )
    return {"project_id": pid}, ""


# Stable order: same as EXPECTED_MCP_TOOL_NAMES sort (audit, drive, projects, requests, transfers).
_LIVE_TOOL_SPECS_RAW: tuple[LiveToolSpec, ...] = (
    LiveToolSpec("audit_get_audit_logs", _audit_get_audit_logs),
    LiveToolSpec("audit_get_audit_logs_for_actor", _audit_get_audit_logs_for_actor),
    LiveToolSpec("audit_get_audit_logs_for_file", _audit_get_audit_logs_for_file),
    LiveToolSpec("drive_complete_drive_upload", _drive_complete_drive_upload),
    LiveToolSpec("drive_create_drive_file_placeholder", _drive_create_drive_file_placeholder),
    LiveToolSpec("drive_create_drive_folder", _drive_create_drive_folder),
    LiveToolSpec("drive_delete_drive_object", _drive_delete_drive_object),
    LiveToolSpec("drive_get_drive_download_url", _drive_get_drive_download_url),
    LiveToolSpec("drive_get_drive_object", _drive_get_drive_object),
    LiveToolSpec("drive_get_drive_upload_url", _drive_get_drive_upload_url),
    LiveToolSpec("drive_list_drive_objects", _drive_list_drive_objects),
    LiveToolSpec("drive_list_object_policy_attachments", _drive_list_object_policy_attachments),
    LiveToolSpec("drive_move_drive_object", _drive_move_drive_object),
    LiveToolSpec("drive_rename_drive_object", _drive_rename_drive_object),
    LiveToolSpec("drive_share_drive_object", _drive_share_drive_object),
    LiveToolSpec("drive_upload_drive_file_from_path", _drive_upload_drive_file_from_path),
    LiveToolSpec("projects_create_project", _projects_create_project),
    LiveToolSpec("projects_delete_project", _projects_delete_project),
    LiveToolSpec("projects_list_projects", _projects_list_projects),
    LiveToolSpec("requests_create_file_request", _requests_create_file_request),
    LiveToolSpec("requests_delete_file_request", _requests_delete_file_request),
    LiveToolSpec("requests_get_file_request", _requests_get_file_request),
    LiveToolSpec("transfers_add_transfer_to_drive", _transfers_add_transfer_to_drive),
    LiveToolSpec("transfers_cancel_multipart_upload", _transfers_cancel_multipart_upload),
    LiveToolSpec("transfers_delete_transfer", _transfers_delete_transfer),
    LiveToolSpec("transfers_finalize_multipart_upload", _transfers_finalize_multipart_upload),
    LiveToolSpec("transfers_get_multipart_presigned_urls", _transfers_get_multipart_presigned_urls),
    LiveToolSpec("transfers_get_transfer", _transfers_get_transfer),
    LiveToolSpec("transfers_get_transfer_public_info", _transfers_get_transfer_public_info),
    LiveToolSpec("transfers_initialize_multipart_upload", _transfers_initialize_multipart_upload),
    LiveToolSpec("transfers_list_transfers", _transfers_list_transfers),
    LiveToolSpec("transfers_share_transfer", _transfers_share_transfer),
    LiveToolSpec(
        "transfers_upload_transfer_multipart_file", _transfers_upload_transfer_multipart_file
    ),
)

LIVE_TOOL_SPECS: tuple[LiveToolSpec, ...] = tuple(
    sorted(_LIVE_TOOL_SPECS_RAW, key=lambda s: s.tool_name),
)

_names = {s.tool_name for s in LIVE_TOOL_SPECS}
if _names != EXPECTED_MCP_TOOL_NAMES:
    missing = EXPECTED_MCP_TOOL_NAMES - _names
    extra = _names - EXPECTED_MCP_TOOL_NAMES
    raise RuntimeError(
        "LIVE_TOOL_SPECS must match EXPECTED_MCP_TOOL_NAMES from mcp_tool_cases. "
        f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
    )
