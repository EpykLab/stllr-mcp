"""HTTP contract for each MCP tool (mock API path + args + expected JSON).

``transfers_upload_transfer_multipart_file`` is covered in
``test_mcp_stdio_multipart_upload.py`` (full initialize → presigned PUTs → finalize chain).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from pytest_httpserver import HTTPServer

# All tool names exposed by the server (namespace + Python function name).
EXPECTED_MCP_TOOL_NAMES: frozenset[str] = frozenset(
    {
        # drive
        "drive_list_drive_objects",
        "drive_get_drive_object",
        "drive_create_drive_folder",
        "drive_create_drive_file_placeholder",
        "drive_rename_drive_object",
        "drive_move_drive_object",
        "drive_delete_drive_object",
        "drive_get_drive_upload_url",
        "drive_complete_drive_upload",
        "drive_upload_drive_file_from_path",
        "drive_get_drive_download_url",
        "drive_share_drive_object",
        "drive_list_object_policy_attachments",
        "drive_attach_policy_to_object",
        "drive_detach_policy_from_object",
        # transfers (upload_transfer_multipart_file: dedicated multipart test)
        "transfers_list_transfers",
        "transfers_get_transfer",
        "transfers_delete_transfer",
        "transfers_share_transfer",
        "transfers_add_transfer_to_drive",
        "transfers_get_transfer_public_info",
        "transfers_initialize_multipart_upload",
        "transfers_get_multipart_presigned_urls",
        "transfers_finalize_multipart_upload",
        "transfers_cancel_multipart_upload",
        "transfers_upload_transfer_multipart_file",
        # requests
        "requests_create_file_request",
        "requests_get_file_request",
        "requests_delete_file_request",
        # projects
        "projects_list_projects",
        "projects_create_project",
        "projects_delete_project",
        # audit
        "audit_get_audit_logs",
        "audit_get_audit_logs_for_actor",
        "audit_get_audit_logs_for_file",
    }
)

# Covered by dedicated integration tests (not single-shot ToolHttpCase).
TOOLS_WITH_DEDICATED_HTTP_INTEGRATION: frozenset[str] = frozenset(
    {
        "transfers_upload_transfer_multipart_file",
        "drive_upload_drive_file_from_path",
    }
)


@dataclass(frozen=True)
class ToolHttpCase:
    """Single MCP ``tools/call`` covered by a matching mock HTTP exchange."""

    tool_name: str
    arguments: dict[str, Any]
    method: str
    path: str
    query: dict[str, str] | None
    status: int
    response: Any
    expected_json: Any

    def register(self, httpserver: HTTPServer) -> None:
        kwargs: dict[str, Any] = {"method": self.method}
        if self.query is not None:
            kwargs["query_string"] = self.query
        handler = httpserver.expect_oneshot_request(self.path, **kwargs)
        if self.status == 204:
            handler.respond_with_data(b"", status=204)
        else:
            handler.respond_with_json(self.response)


# fmt: off
TOOL_HTTP_CASES: tuple[ToolHttpCase, ...] = (
    ToolHttpCase(
        "drive_list_drive_objects",
        {"project_id": 1},
        "GET", "/api/v1/objects",
        {"project_id": "1"},
        200, [{"id": 10, "name": "a", "type": "FILE"}],
        [{"id": 10, "name": "a", "type": "FILE"}],
    ),
    ToolHttpCase(
        "drive_get_drive_object",
        {"object_id": 5},
        "GET", "/api/v1/objects/5",
        None,
        200, {"id": 5, "name": "o", "type": "FOLDER"},
        {"id": 5, "name": "o", "type": "FOLDER"},
    ),
    ToolHttpCase(
        "drive_create_drive_folder",
        {"project_id": 1, "name": "nf"},
        "POST", "/api/v1/objects",
        None,
        200, {"id": 20, "type": "FOLDER"},
        {"id": 20, "type": "FOLDER"},
    ),
    ToolHttpCase(
        "drive_create_drive_file_placeholder",
        {"project_id": 1, "name": "f.pdf", "mime_type": "application/pdf"},
        "POST", "/api/v1/objects",
        None,
        200, {"id": 21, "type": "FILE"},
        {"id": 21, "type": "FILE"},
    ),
    ToolHttpCase(
        "drive_rename_drive_object",
        {"object_id": 7, "new_name": "renamed.txt"},
        "PATCH", "/api/v1/objects/7",
        None,
        200, {"id": 7, "name": "renamed.txt"},
        {"id": 7, "name": "renamed.txt"},
    ),
    ToolHttpCase(
        "drive_move_drive_object",
        {"object_id": 8, "new_parent_id": 3},
        "PATCH", "/api/v1/objects/8",
        None,
        200, {"id": 8, "parentId": 3},
        {"id": 8, "parentId": 3},
    ),
    ToolHttpCase(
        "drive_delete_drive_object",
        {"object_id": 9},
        "DELETE", "/api/v1/objects/9",
        None,
        200,
        {"data": {"id": 9, "name": "gone.txt", "type": "FILE"}, "error": None},
        {"id": 9, "name": "gone.txt", "type": "FILE"},
    ),
    ToolHttpCase(
        "drive_get_drive_upload_url",
        {"object_id": 11},
        "GET", "/api/v1/objects/11/upload-url",
        None,
        200, {"url": "https://s3.example/presigned-put"},
        {"url": "https://s3.example/presigned-put"},
    ),
    ToolHttpCase(
        "drive_complete_drive_upload",
        {
            "object_id": 12,
            "bucket": "test-bucket",
            "etag": "abc123",
            "size_bytes": 1024,
        },
        "POST", "/api/v1/objects/12/upload/complete",
        None,
        200, {"ok": True},
        {"ok": True},
    ),
    ToolHttpCase(
        "drive_get_drive_download_url",
        {"object_id": 13},
        "GET", "/api/v1/objects/13/download-url",
        None,
        200, {"url": "https://s3.example/presigned-get"},
        {"url": "https://s3.example/presigned-get"},
    ),
    ToolHttpCase(
        "drive_share_drive_object",
        {"object_id": 14, "recipient_email": "r@example.com"},
        "POST", "/api/v1/objects/14/share",
        None,
        200, {"shared": True},
        {"shared": True},
    ),
    ToolHttpCase(
        "drive_list_object_policy_attachments",
        {"object_id": 15},
        "GET", "/api/v1/objects/15/policy-attachments",
        None,
        200, [{"policyId": "p1"}],
        [{"policyId": "p1"}],
    ),
    ToolHttpCase(
        "drive_attach_policy_to_object",
        {"object_id": 16, "policy_id": 9},
        "POST", "/api/v1/objects/16/policy-attachments",
        None,
        200, {"attachmentId": "att-1"},
        {"attachmentId": "att-1"},
    ),
    ToolHttpCase(
        "drive_detach_policy_from_object",
        {"object_id": 17, "attachment_id": "att-2"},
        "DELETE", "/api/v1/objects/17/policy-attachments/att-2",
        None,
        204, None,
        None,
    ),
    ToolHttpCase(
        "transfers_list_transfers",
        {},
        "GET", "/api/v1/transfers",
        None,
        200, [{"id": "tr1"}],
        [{"id": "tr1"}],
    ),
    ToolHttpCase(
        "transfers_get_transfer",
        {"transfer_id": "tid-1"},
        "GET", "/api/v1/transfers/tid-1",
        None,
        200, {"id": "tid-1", "size": 100},
        {"id": "tid-1", "size": 100},
    ),
    ToolHttpCase(
        "transfers_delete_transfer",
        {"transfer_id": "tid-2"},
        "DELETE", "/api/v1/transfers/tid-2",
        None,
        204, None,
        None,
    ),
    ToolHttpCase(
        "transfers_share_transfer",
        {"transfer_id": "tid-3", "recipient_email": "x@y.com"},
        "POST", "/api/v1/bridge/transfers/tid-3/share",
        None,
        200, {"ok": True},
        {"ok": True},
    ),
    ToolHttpCase(
        "transfers_add_transfer_to_drive",
        {"transfer_id": "tid-4", "project_id": 1},
        "POST", "/api/v1/bridge/transfers/tid-4/add-to-drive",
        None,
        200, {"objectId": 30},
        {"objectId": 30},
    ),
    ToolHttpCase(
        "transfers_get_transfer_public_info",
        {"transfer_id": "pub-1"},
        "GET", "/api/v1/public/download/info/pub-1",
        None,
        200, {"bytesTotal": 50},
        {"bytesTotal": 50},
    ),
    ToolHttpCase(
        "transfers_initialize_multipart_upload",
        {"file_name": "big.bin", "size_bytes": 9_000_000},
        "POST", "/api/v1/bridge/uploads/initialize-multipart-upload",
        None,
        200, {"fileId": "u1", "fileKey": "k1"},
        {"fileId": "u1", "fileKey": "k1"},
    ),
    ToolHttpCase(
        "transfers_get_multipart_presigned_urls",
        {"upload_id": "u1", "file_key": "k1", "parts": 3},
        "POST", "/api/v1/bridge/uploads/get-multipart-presigned-urls",
        None,
        200, {"urls": [1, 2, 3]},
        {"urls": [1, 2, 3]},
    ),
    ToolHttpCase(
        "transfers_finalize_multipart_upload",
        {
            "upload_id": "u1",
            "file_key": "k1",
            "parts": [{"PartNumber": 1, "ETag": "e"}],
            "size_bytes": 100,
        },
        "POST", "/api/v1/bridge/uploads/finalize-multipart-upload",
        None,
        200, {"transferId": "done"},
        {"transferId": "done"},
    ),
    ToolHttpCase(
        "transfers_cancel_multipart_upload",
        {"upload_id": "u2", "file_key": "k2"},
        "POST", "/api/v1/bridge/uploads/cancel",
        None,
        200, {"cancelled": True},
        {"cancelled": True},
    ),
    ToolHttpCase(
        "requests_create_file_request",
        {"title": "Please upload", "recipient_email": "u@example.com"},
        "POST", "/api/v1/bridge/transfer/request/create",
        None,
        200,
        {"data": {"requestId": "req-1"}, "error": None},
        {"requestId": "req-1"},
    ),
    ToolHttpCase(
        "requests_get_file_request",
        {"request_id": "req-2"},
        "GET", "/api/v1/bridge/transfer/request/get/req-2",
        None,
        200, {"id": "req-2", "status": "OPEN"},
        {"id": "req-2", "status": "OPEN"},
    ),
    ToolHttpCase(
        "requests_delete_file_request",
        {"request_id": "req-3"},
        "DELETE", "/api/v1/bridge/transfer/request/delete/req-3",
        None,
        204, None,
        None,
    ),
    ToolHttpCase(
        "projects_list_projects",
        {},
        "GET", "/api/v1/projects",
        None,
        200, [{"id": 1, "name": "P1"}],
        [{"id": 1, "name": "P1"}],
    ),
    ToolHttpCase(
        "projects_create_project",
        {"name": "NewP", "partner_ids": [1, 2]},
        "POST", "/api/v1/projects",
        None,
        200, {"id": 40, "name": "NewP"},
        {"id": 40, "name": "NewP"},
    ),
    ToolHttpCase(
        "projects_delete_project",
        {"project_id": 41},
        "DELETE", "/api/v1/projects/41",
        None,
        200,
        {"data": {"id": 41, "name": "OldP", "slug": "old-p"}, "error": None},
        {"id": 41, "name": "OldP", "slug": "old-p"},
    ),
    ToolHttpCase(
        "audit_get_audit_logs",
        {},
        "GET", "/api/v1/logs",
        None,
        200, [{"id": "log-1"}],
        [{"id": "log-1"}],
    ),
    ToolHttpCase(
        "audit_get_audit_logs_for_actor",
        {"actor_id": "user-9"},
        "GET", "/api/v1/logs",
        {"actor": "user-9"},
        200, [{"id": "log-a"}],
        [{"id": "log-a"}],
    ),
    ToolHttpCase(
        "audit_get_audit_logs_for_file",
        {"file_name": "secret.doc"},
        "GET", "/api/v1/logs",
        {"fileName": "secret.doc"},
        200, [{"id": "log-f"}],
        [{"id": "log-f"}],
    ),
)
# fmt: on

# Mock tools whose HTTP contract is 204 with no JSON body; live MCP may return no
# parseable structured content (``json_from_tool_result`` is ``None``).
LIVE_OPTIONAL_JSON_PAYLOAD_TOOLS: Final[frozenset[str]] = frozenset(
    c.tool_name for c in TOOL_HTTP_CASES if c.expected_json is None
)


def assert_cases_cover_all_http_tools() -> None:
    """Guardrail: every registered tool has either a ToolHttpCase or a dedicated integration test."""
    covered = {c.tool_name for c in TOOL_HTTP_CASES} | TOOLS_WITH_DEDICATED_HTTP_INTEGRATION
    expected = EXPECTED_MCP_TOOL_NAMES
    missing = expected - covered
    extra = covered - expected
    assert not missing, f"missing coverage for tools: {missing}"
    assert not extra, f"unknown tool names in coverage sets: {extra}"


assert_cases_cover_all_http_tools()
