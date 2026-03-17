"""MCP tools for Transfer (bridge) operations."""

from typing import Annotated, Any

from fastmcp import FastMCP

from ..client import get_client

mcp: FastMCP = FastMCP("stellarbridge-transfers")


@mcp.tool()
def list_transfers(
    org_id: Annotated[str | None, "Filter transfers by organisation ID"] = None,
) -> Any:
    """List file transfers, optionally filtered by organisation."""
    return get_client().list_transfers(org_id)


@mcp.tool()
def get_transfer(
    transfer_id: Annotated[str, "ID of the transfer to retrieve"],
) -> Any:
    """Get metadata for a single transfer (size, expiry, created_at, etc.)."""
    return get_client().get_transfer(transfer_id)


@mcp.tool()
def delete_transfer(
    transfer_id: Annotated[str, "ID of the transfer to delete"],
) -> Any:
    """Delete a transfer and its associated files."""
    return get_client().delete_transfer(transfer_id)


@mcp.tool()
def share_transfer(
    transfer_id: Annotated[str, "ID of the transfer to share"],
    recipient_email: Annotated[str, "Email address of the recipient"],
) -> Any:
    """Share an existing transfer with a recipient by email."""
    return get_client().share_transfer(transfer_id, recipient_email)


@mcp.tool()
def add_transfer_to_drive(
    transfer_id: Annotated[str, "ID of the completed transfer"],
    project_id: Annotated[int, "Drive project to add the file into"],
    parent_id: Annotated[int | None, "Folder ID within the project; omit for root"] = None,
) -> Any:
    """Move a completed transfer into a Drive project folder."""
    return get_client().add_transfer_to_drive(transfer_id, project_id, parent_id)


@mcp.tool()
def get_transfer_public_info(
    transfer_id: Annotated[str, "Public transfer ID"],
) -> Any:
    """Get public metadata about a transfer (no authentication required)."""
    return get_client().get_transfer_public_info(transfer_id)


@mcp.tool()
def initialize_multipart_upload(
    file_name: Annotated[str, "Name of the file being uploaded"],
    mime_type: Annotated[str, "MIME type, e.g. application/pdf"],
    size_bytes: Annotated[int, "Total file size in bytes"],
    expiry_hours: Annotated[int | None, "Hours until transfer expires (default: server default)"] = None,
) -> Any:
    """Initialise a multipart upload for a new transfer.

    Returns an upload ID and other metadata needed for subsequent calls to
    get_multipart_presigned_urls and finalize_multipart_upload.
    """
    payload: dict[str, Any] = {
        "fileName": file_name,
        "mimeType": mime_type,
        "sizeBytes": size_bytes,
    }
    if expiry_hours is not None:
        payload["expiryHours"] = expiry_hours
    return get_client().initialize_multipart_upload(payload)


@mcp.tool()
def get_multipart_presigned_urls(
    upload_id: Annotated[str, "Upload ID from initialize_multipart_upload"],
    s3_key: Annotated[str, "S3 key from initialize_multipart_upload"],
    s3_bucket: Annotated[str, "S3 bucket from initialize_multipart_upload"],
    part_numbers: Annotated[list[int], "List of part numbers (1-based) to get URLs for"],
) -> Any:
    """Get presigned PUT URLs for individual parts of a multipart upload."""
    return get_client().get_multipart_presigned_urls(
        {
            "uploadId": upload_id,
            "s3Key": s3_key,
            "s3Bucket": s3_bucket,
            "partNumbers": part_numbers,
        }
    )


@mcp.tool()
def finalize_multipart_upload(
    upload_id: Annotated[str, "Upload ID from initialize_multipart_upload"],
    s3_key: Annotated[str, "S3 key from initialize_multipart_upload"],
    s3_bucket: Annotated[str, "S3 bucket from initialize_multipart_upload"],
    parts: Annotated[
        list[dict[str, Any]],
        'Completed parts list, each with "PartNumber" (int) and "ETag" (str)',
    ],
) -> Any:
    """Finalise a multipart upload after all parts have been PUT to S3."""
    return get_client().finalize_multipart_upload(
        {
            "uploadId": upload_id,
            "s3Key": s3_key,
            "s3Bucket": s3_bucket,
            "parts": parts,
        }
    )


@mcp.tool()
def cancel_multipart_upload(
    upload_id: Annotated[str, "Upload ID to cancel"],
    s3_key: Annotated[str, "S3 key from initialize_multipart_upload"],
    s3_bucket: Annotated[str, "S3 bucket from initialize_multipart_upload"],
) -> Any:
    """Cancel an in-progress multipart upload and clean up S3 resources."""
    return get_client().cancel_multipart_upload(
        {"uploadId": upload_id, "s3Key": s3_key, "s3Bucket": s3_bucket}
    )
