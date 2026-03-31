"""Integration: ``transfers_upload_transfer_multipart_file`` with repo fixture + mocked API + mock S3 PUT."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from .mcp_stdio_helpers import first_json_from_tool_content

# Committed bytes: 1024 bytes, bytes(i % 256) for i in range(1024) — see tests/fixtures/uploads/
MULTIPART_FIXTURE_RELATIVE = Path("tests/fixtures/uploads/multipart_upload.bin")
MULTIPART_FIXTURE_SIZE = 1024


@pytest.mark.integration
async def test_upload_transfer_multipart_file_end_to_end(
    httpserver: HTTPServer,
    stellarbridge_api_env: dict[str, str],
    repo_root: Path,
) -> None:
    """Initialize → presigned URLs (pointing at this server) → PUT part → finalize."""
    fixture_path = (repo_root / MULTIPART_FIXTURE_RELATIVE).resolve()
    assert fixture_path.is_file(), f"missing committed fixture: {fixture_path}"
    assert fixture_path.stat().st_size == MULTIPART_FIXTURE_SIZE
    expected_body = fixture_path.read_bytes()

    s3_put_path = "/__mock_s3__/multipart/part1"
    s3_put_url = httpserver.url_for(s3_put_path)

    httpserver.expect_oneshot_request(
        "/api/v1/bridge/uploads/initialize-multipart-upload",
        method="POST",
    ).respond_with_json(
        {"fileId": "integration-file-id", "fileKey": "integration-file-key"},
    )

    httpserver.expect_oneshot_request(
        "/api/v1/bridge/uploads/get-multipart-presigned-urls",
        method="POST",
    ).respond_with_json({"urls": [s3_put_url]})

    def on_s3_put(request: Request) -> Response:
        assert request.method == "PUT"
        assert request.get_data() == expected_body
        return Response(
            status=200,
            headers={"ETag": '"etag-integration-part-1"'},
        )

    httpserver.expect_oneshot_request(s3_put_path, method="PUT").respond_with_handler(on_s3_put)

    finalize_payload = {"transferId": "integration-transfer-done", "status": "COMPLETE"}
    httpserver.expect_oneshot_request(
        "/api/v1/bridge/uploads/finalize-multipart-upload",
        method="POST",
    ).respond_with_json(finalize_payload)

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
                "transfers_upload_transfer_multipart_file",
                {"file_path": str(fixture_path)},
            )

    assert not result.isError
    data = first_json_from_tool_content(result.content)
    assert data == finalize_payload
    assert len(httpserver.log) == 4
