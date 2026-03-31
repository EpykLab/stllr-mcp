"""MCP tools for file request operations."""

from typing import Annotated, Any

from fastmcp import FastMCP

from ..client import get_client

mcp: FastMCP = FastMCP("stellarbridge-requests")


@mcp.tool()
def create_file_request(
    title: Annotated[str, "Human-readable title for the upload request"],
    recipient_email: Annotated[str, "Email of the person being asked to upload"],
    message: Annotated[str | None, "Optional message to include in the request email"] = None,
    expiry_hours: Annotated[int | None, "Hours until the request link expires"] = None,
    project_id: Annotated[int | None, "Drive project to receive the uploaded file"] = None,
    parent_id: Annotated[int | None, "Folder within the project to place the uploaded file"] = None,
) -> Any:
    """Create a file upload request to send to an external user.

    The recipient receives a link to upload a file without needing a
    Stellarbridge account.  If project_id is supplied the uploaded file
    is automatically added to the specified Drive folder on completion.
    """
    payload: dict[str, Any] = {"title": title, "recipientEmail": recipient_email}
    if message:
        payload["message"] = message
    if expiry_hours is not None:
        payload["expiryHours"] = expiry_hours
    if project_id is not None:
        payload["projectId"] = project_id
    if parent_id is not None:
        payload["parentId"] = parent_id
    return get_client().create_file_request(payload)


@mcp.tool()
def get_file_request(
    request_id: Annotated[str, "ID of the file request to retrieve"],
) -> Any:
    """Get details and status of a file upload request."""
    return get_client().get_file_request(request_id)


@mcp.tool()
def delete_file_request(
    request_id: Annotated[str, "ID of the file request to delete"],
) -> Any:
    """Delete a file upload request, invalidating the recipient's upload link."""
    return get_client().delete_file_request(request_id)
