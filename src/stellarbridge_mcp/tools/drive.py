"""MCP tools for Drive / VFS operations."""

from typing import Annotated, Any

from fastmcp import FastMCP

from ..client import get_client

mcp: FastMCP = FastMCP("stellarbridge-drive")


@mcp.tool()
def list_drive_objects(
    project_id: Annotated[int, "ID of the project (top-level container)"],
    parent_id: Annotated[int | None, "Folder ID to list children of; omit for root"] = None,
) -> Any:
    """List files and folders inside a Drive project folder.

    Returns an array of object metadata records including id, name, type
    (FILE or FOLDER), size, and creation time.
    """
    return get_client().list_objects(project_id, parent_id)


@mcp.tool()
def get_drive_object(
    object_id: Annotated[int, "ID of the file or folder to retrieve"],
) -> Any:
    """Get metadata for a single Drive object (file or folder)."""
    return get_client().get_object(object_id)


@mcp.tool()
def create_drive_folder(
    project_id: Annotated[int, "Project the folder belongs to"],
    name: Annotated[str, "Folder name"],
    parent_id: Annotated[int | None, "Parent folder ID; omit to create at project root"] = None,
) -> Any:
    """Create a new folder inside a Drive project."""
    payload: dict[str, Any] = {"type": "FOLDER", "projectId": project_id, "name": name}
    if parent_id is not None:
        payload["parentId"] = parent_id
    return get_client().create_object(payload)


@mcp.tool()
def create_drive_file_placeholder(
    project_id: Annotated[int, "Project the file belongs to"],
    name: Annotated[str, "File name including extension"],
    mime_type: Annotated[str, "MIME type of the file, e.g. application/pdf"],
    parent_id: Annotated[int | None, "Parent folder ID; omit for project root"] = None,
) -> Any:
    """Create a file placeholder in Drive before uploading content.

    After creating the placeholder use get_drive_upload_url to obtain a
    presigned S3 PUT URL, upload the file bytes directly to that URL, then
    call complete_drive_upload to finalise the object.
    """
    payload: dict[str, Any] = {
        "type": "FILE",
        "projectId": project_id,
        "name": name,
        "mimeType": mime_type,
    }
    if parent_id is not None:
        payload["parentId"] = parent_id
    return get_client().create_object(payload)


@mcp.tool()
def rename_drive_object(
    object_id: Annotated[int, "ID of the object to rename"],
    new_name: Annotated[str, "New name for the object"],
) -> Any:
    """Rename a Drive file or folder."""
    return get_client().update_object(object_id, {"name": new_name})


@mcp.tool()
def move_drive_object(
    object_id: Annotated[int, "ID of the object to move"],
    new_parent_id: Annotated[
        int | None,
        "Destination folder ID; omit this argument to move to the project root. Do not use 0.",
    ] = None,
) -> Any:
    """Move a Drive file or folder to another folder or to the project root.

    Project root matches list_drive_objects (no parent) and create_drive_folder
    (omit parent): pass no destination folder ID, not 0.
    """
    if new_parent_id == 0:
        raise ValueError(
            "new_parent_id cannot be 0. Omit new_parent_id (or pass null) to move to the "
            "project root, or pass the real folder ID of the destination."
        )
    return get_client().update_object(object_id, {"parentId": new_parent_id})


@mcp.tool()
def delete_drive_object(
    object_id: Annotated[int, "ID of the file or folder to delete"],
) -> Any:
    """Soft-delete a Drive file or folder.

    The object is marked as deleted and excluded from listings but is not
    immediately purged from storage.
    """
    return get_client().delete_object(object_id)


@mcp.tool()
def get_drive_upload_url(
    object_id: Annotated[int, "ID of the file placeholder to upload content to"],
) -> Any:
    """Get a presigned S3 PUT URL for uploading file content to a Drive object.

    Use this after creating a file placeholder with create_drive_file_placeholder.
    Upload the file bytes via HTTP PUT to the returned URL, then call
    complete_drive_upload.
    """
    return get_client().get_upload_url(object_id)


@mcp.tool()
def complete_drive_upload(
    object_id: Annotated[int, "ID of the file object whose upload is complete"],
) -> Any:
    """Finalise a Drive file upload after content has been PUT to the presigned URL.

    Must be called after uploading bytes to the presigned URL returned by
    get_drive_upload_url.
    """
    return get_client().complete_upload(object_id)


@mcp.tool()
def get_drive_download_url(
    object_id: Annotated[int, "ID of the file to download"],
) -> Any:
    """Get a presigned S3 GET URL for downloading a Drive file.

    The URL is time-limited and subject to any policy restrictions attached
    to the object.
    """
    return get_client().get_download_url(object_id)


@mcp.tool()
def share_drive_object(
    object_id: Annotated[int, "ID of the Drive file or folder to share"],
    recipient_email: Annotated[str, "Email address of the recipient"],
) -> Any:
    """Share a Drive file or folder with an external recipient by email."""
    return get_client().share_object(object_id, recipient_email)


@mcp.tool()
def list_object_policy_attachments(
    object_id: Annotated[int, "ID of the Drive object"],
) -> Any:
    """List all policies currently attached to a Drive object."""
    return get_client().list_policy_attachments(object_id)


@mcp.tool()
def attach_policy_to_object(
    object_id: Annotated[int, "ID of the Drive object"],
    policy_id: Annotated[int, "Numeric access policy ID to attach"],
) -> Any:
    """Attach an access-control policy to a Drive file or folder."""
    return get_client().attach_policy(object_id, policy_id)


@mcp.tool()
def detach_policy_from_object(
    object_id: Annotated[int, "ID of the Drive object"],
    attachment_id: Annotated[str, "ID of the policy attachment to remove"],
) -> Any:
    """Remove a policy attachment from a Drive file or folder."""
    return get_client().detach_policy(object_id, attachment_id)
