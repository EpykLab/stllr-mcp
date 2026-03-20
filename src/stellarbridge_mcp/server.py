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
        "actions with the user before proceeding."
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
