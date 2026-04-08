"""MCP tools for audit log retrieval.

The Stellarbridge API exposes audit logs at GET /logs (JWT auth) and also
at GET /audit with a direct X-API-Key header (SIEM-oriented endpoint).
Both paths are supported here.

Response objects follow the OpenAPI AuditLog shape (GET /api/v1/logs):
  id, timestamp, actor, actorType (human|agent|api), action,
  fileName, fileHash, orgId, userId, flowId
"""

from typing import Annotated, Any

from fastmcp import FastMCP

from ..client import get_client
from ..config import settings

mcp: FastMCP = FastMCP("stellarbridge-audit")


@mcp.tool()
def get_audit_logs(
    start_time: Annotated[
        str | None, "Start of time range in ISO 8601 format, e.g. 2025-01-01T00:00:00Z"
    ] = None,
    end_time: Annotated[
        str | None, "End of time range in ISO 8601 format, e.g. 2025-12-31T23:59:59Z"
    ] = None,
    actor: Annotated[
        str | None,
        "Filter by actor (UPN/email or user/identity id) who performed the action",
    ] = None,
    file_name: Annotated[
        str | None,
        "Filter by file label: matches sender attachment name or target name (e.g. VFS object)",
    ] = None,
    file_hash: Annotated[str | None, "Filter by hash of the file involved"] = None,
    org_id: Annotated[str | None, "Filter by organisation ID"] = None,
    user_id: Annotated[str | None, "Filter by user ID"] = None,
    limit: Annotated[
        int | None, "Maximum number of results to return (1-1000, default 50)"
    ] = None,
) -> Any:
    """Retrieve audit log entries with optional filters.

    Logs capture authentication events, file transfer events (upload/download),
    user management changes, organisation events, and API access events.

    Each log entry contains:
    - id: unique entry ID
    - timestamp: ISO 8601 event time
    - actor: user ID of who performed the action
    - actorType: one of "human", "agent", or "api"
    - action: type of action performed
    - fileName / fileHash: file involved if applicable; fileName is sender
      attachment name or target name when sender is empty
    - orgId / userId: organisation and user context

    Use start_time / end_time to scope queries to a time window.  Large
    result sets should be paginated via limit.
    """
    filters: dict[str, Any] = {}
    if start_time:
        filters["startTime"] = start_time
    if end_time:
        filters["endTime"] = end_time
    if actor:
        filters["actor"] = actor
    if file_name:
        filters["fileName"] = file_name
    if file_hash:
        filters["fileHash"] = file_hash
    if org_id:
        filters["orgId"] = org_id
    if user_id:
        filters["userId"] = user_id
    if limit is not None:
        filters["limit"] = max(1, min(limit, 1000))

    return get_client().get_audit_logs(**filters)


@mcp.tool()
def get_audit_logs_for_actor(
    actor_id: Annotated[
        str,
        "Actor to look up (UPN/email or user/identity id)",
    ],
    start_time: Annotated[
        str | None, "Start of time range in ISO 8601 format"
    ] = None,
    end_time: Annotated[
        str | None, "End of time range in ISO 8601 format"
    ] = None,
    limit: Annotated[int | None, "Maximum results (1-1000)"] = None,
) -> Any:
    """Retrieve all audit log entries for a specific actor (user or identity).

    Convenience wrapper around get_audit_logs scoped to a single actor —
    useful for investigating what a particular user or agent identity has done.
    """
    filters: dict[str, Any] = {"actor": actor_id}
    if start_time:
        filters["startTime"] = start_time
    if end_time:
        filters["endTime"] = end_time
    if limit is not None:
        filters["limit"] = max(1, min(limit, 1000))
    return get_client().get_audit_logs(**filters)


@mcp.tool()
def get_audit_logs_for_file(
    file_name: Annotated[str | None, "File name to search for"] = None,
    file_hash: Annotated[str | None, "SHA256 or other hash of the file"] = None,
    start_time: Annotated[str | None, "Start of time range in ISO 8601 format"] = None,
    end_time: Annotated[str | None, "End of time range in ISO 8601 format"] = None,
    limit: Annotated[int | None, "Maximum results (1-1000)"] = None,
) -> Any:
    """Retrieve audit log entries related to a specific file.

    Provide file_name, file_hash, or both to narrow results.  Useful for
    chain-of-custody investigations on a particular file.
    """
    if not file_name and not file_hash:
        raise ValueError("At least one of file_name or file_hash must be provided.")
    filters: dict[str, Any] = {}
    if file_name:
        filters["fileName"] = file_name
    if file_hash:
        filters["fileHash"] = file_hash
    if start_time:
        filters["startTime"] = start_time
    if end_time:
        filters["endTime"] = end_time
    if limit is not None:
        filters["limit"] = max(1, min(limit, 1000))
    return get_client().get_audit_logs(**filters)
