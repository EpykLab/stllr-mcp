"""Stellarbridge MCP server entry point.

Registers all tool sub-modules and exposes a single FastMCP application
that can be run via stdio (default) or SSE transport.

Environment variables (all prefixed STELLARBRIDGE_):
  API_URL         Base URL of the Stellarbridge API  (default: http://localhost:8080)
  API_KEY         API key to exchange for a JWT token
  JWT_TOKEN       Pre-supplied JWT token (skips /auth exchange)
  HTTP_TIMEOUT    HTTP timeout in seconds              (default: 30)
"""

from fastmcp import FastMCP

from .tools.audit import mcp as audit_mcp
from .tools.drive import mcp as drive_mcp
from .tools.projects import mcp as projects_mcp
from .tools.requests import mcp as requests_mcp
from .tools.transfers import mcp as transfers_mcp

# ---------------------------------------------------------------------------
# Root server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "stellarbridge",
    instructions=(
        "You are connected to the Stellarbridge secure file platform. "
        "Use the available tools to manage Drive files and folders, send and "
        "receive file transfers, handle file upload requests, and query audit "
        "logs. Always prefer least-privilege operations and confirm destructive "
        "actions with the user before proceeding. "
        "Tool names are namespaced (e.g. drive_*): use the exact names from "
        "tools/list, not shortened Python names. "
        "Drive file uploads use a presigned-URL flow: drive_create_drive_file_placeholder, "
        "then drive_get_drive_upload_url, then HTTP PUT file bytes to the returned URL "
        "(outside MCP—not via tool arguments), then drive_complete_drive_upload with "
        "bucket, ETag from the PUT response, and size_bytes. "
        "If a file path exists on the MCP server host, prefer drive_upload_drive_file_from_path "
        "on a FILE placeholder so the server performs PUT and complete for you."
    ),
)

# Mount sub-servers with explicit keyword args (FastMCP 3: server=, namespace=).
mcp.mount(server=drive_mcp, namespace="drive")
mcp.mount(server=transfers_mcp, namespace="transfers")
mcp.mount(server=requests_mcp, namespace="requests")
mcp.mount(server=projects_mcp, namespace="projects")
mcp.mount(server=audit_mcp, namespace="audit")


def main() -> None:
    """CLI entry point – runs the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
