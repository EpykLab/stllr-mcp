"""MCP tools for project and partner management."""

from typing import Annotated, Any

from fastmcp import FastMCP

from ..client import get_client

mcp: FastMCP = FastMCP("stellarbridge-projects")


@mcp.tool()
def list_projects() -> Any:
    """List all Drive projects accessible to the authenticated identity."""
    return get_client().list_projects()


@mcp.tool()
def create_project(
    name: Annotated[str, "Name of the new project"],
    partner_ids: Annotated[
        list[int], "List of partner organisation IDs to include in the project"
    ],
) -> Any:
    """Create a new Drive project and associate it with one or more partners."""
    return get_client().create_project(name, partner_ids)


@mcp.tool()
def delete_project(
    project_id: Annotated[int, "ID of the project to delete"],
) -> Any:
    """Delete a Drive project.

    This will fail if the project still contains files or folders.  Remove
    all objects first before deleting the project.
    """
    return get_client().delete_project(project_id)
