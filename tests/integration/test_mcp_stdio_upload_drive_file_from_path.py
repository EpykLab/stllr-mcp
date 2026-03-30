"""Integration: ``drive_upload_drive_file_from_path`` with fixture file + mocked API + mock S3 PUT."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from .mcp_stdio_helpers import first_json_from_tool_content

FIXTURE_RELATIVE = Path("tests/fixtures/uploads/multipart_upload.bin")
FIXTURE_SIZE = 1024


@pytest.mark.integration
async def test_upload_drive_file_from_path_end_to_end(
    httpserver: HTTPServer,
    stellarbridge_api_env: dict[str, str],
    repo_root: Path,
) -> None:
    """GET upload-url → PUT bytes to presigned URL → POST upload/complete."""
    fixture_path = (repo_root / FIXTURE_RELATIVE).resolve()
    assert fixture_path.is_file(), f"missing committed fixture: {fixture_path}"
    expected_body = fixture_path.read_bytes()
    assert len(expected_body) == FIXTURE_SIZE

    object_id = 99
    s3_put_path = "/__mock_s3__/drive_put"
    s3_put_url = httpserver.url_for(s3_put_path)

    httpserver.expect_oneshot_request(
        f"/api/v1/objects/{object_id}/upload-url",
        method="GET",
    ).respond_with_json(
        {"bucket": "integration-bucket", "upload_url": s3_put_url},
    )

    def on_s3_put(request: Request) -> Response:
        assert request.method == "PUT"
        assert request.get_data() == expected_body
        return Response(
            status=200,
            headers={"ETag": '"etag-drive-integration"'},
        )

    httpserver.expect_oneshot_request(s3_put_path, method="PUT").respond_with_handler(on_s3_put)

    complete_payload = {"data": {"id": str(object_id), "etag": "etag-drive-integration"}}
    httpserver.expect_oneshot_request(
        f"/api/v1/objects/{object_id}/upload/complete",
        method="POST",
    ).respond_with_json(complete_payload)

    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "stellarbridge_mcp"],
        env=stellarbridge_api_env,
        cwd=str(repo_root),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "drive_upload_drive_file_from_path",
                {
                    "object_id": object_id,
                    "file_path": str(fixture_path),
                    "content_type": "application/octet-stream",
                },
            )

    assert not result.isError
    data = first_json_from_tool_content(result.content)
    assert data["object_id"] == object_id
    assert data["size_bytes"] == FIXTURE_SIZE
    assert data["bucket"] == "integration-bucket"
    assert data["etag"] == "etag-drive-integration"
    assert data["complete"] == complete_payload
    assert len(httpserver.log) == 3
