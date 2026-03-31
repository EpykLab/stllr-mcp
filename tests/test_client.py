"""Tests for the StellarBridgeClient.

The current client authenticates by sending X-API-Key on every request.
"""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_httpx

from stellarbridge_mcp import config
from stellarbridge_mcp.client import StellarBridgeClient


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch: pytest.MonkeyPatch):
    """Reset settings to known values for each test."""
    monkeypatch.setattr(config.settings, "api_url", "http://localhost:8080")
    monkeypatch.setattr(config.settings, "api_key", "test-api-key")
    monkeypatch.setattr(config.settings, "jwt_token", "")
    monkeypatch.setattr(config.settings, "http_timeout", 5.0)


class TestRequestHeaders:
    def test_sends_x_api_key_header(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/projects",
            json={"data": {"projects": []}, "error": None},
        )
        client = StellarBridgeClient()
        client.list_projects()

        req = httpx_mock.get_requests()[0]
        assert req.headers.get("X-API-Key") == "test-api-key"

    def test_raises_without_api_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(config.settings, "api_key", "")
        client = StellarBridgeClient()
        with pytest.raises(RuntimeError, match="No API key configured"):
            client.list_projects()


class TestBaseUrl:
    def test_trailing_slash_stripped(self, monkeypatch: pytest.MonkeyPatch, httpx_mock):
        monkeypatch.setattr(config.settings, "api_url", "http://localhost:8080/")
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/projects",
            json={"data": {"projects": []}, "error": None},
        )
        client = StellarBridgeClient()
        client.list_projects()
        req = httpx_mock.get_requests()[0]
        assert str(req.url) == "http://localhost:8080/api/v1/projects"


class TestCreateProject:
    def test_post_json_uses_partner_ids(self, httpx_mock: pytest_httpx.HTTPXMock):
        """POST /projects body must use partner_ids (snake_case) per API contract."""
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/projects",
            json={"data": {"id": 1, "name": "P"}, "error": None},
        )
        client = StellarBridgeClient()
        client.create_project("My Project", [1, 2])
        req = httpx_mock.get_requests()[0]
        assert json.loads(req.content) == {"name": "My Project", "partner_ids": [1, 2]}


class TestListObjects:
    def test_without_parent(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/objects?project_id=5",
            json={"data": {"objects": [{"id": 10, "name": "root"}]}, "error": None},
        )
        client = StellarBridgeClient()
        result = client.list_objects(5)
        assert result["data"]["objects"][0]["name"] == "root"

    def test_params_omit_none(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Request params with None values are omitted from the query string."""
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/objects?project_id=5",
            json={"data": {"objects": []}, "error": None},
        )
        client = StellarBridgeClient()
        client.list_objects(5)
        req = httpx_mock.get_requests()[0]
        assert "parent_id" not in str(req.url)


class TestRequestBehavior:
    def test_raises_on_4xx(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/objects/999",
            status_code=404,
        )
        client = StellarBridgeClient()
        with pytest.raises(httpx.HTTPStatusError):
            client.get_object(999)

    def test_returns_none_for_empty_delete_response(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="DELETE",
            url="http://localhost:8080/api/v1/objects/1",
            status_code=200,
            content=b"",
        )
        client = StellarBridgeClient()
        assert client.delete_object(1) is None

    def test_delete_object_unwraps_api_envelope(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="DELETE",
            url="http://localhost:8080/api/v1/objects/1",
            status_code=200,
            json={
                "data": {"id": 1, "name": "a.txt", "type": "FILE"},
                "error": None,
            },
        )
        client = StellarBridgeClient()
        assert client.delete_object(1) == {
            "id": 1,
            "name": "a.txt",
            "type": "FILE",
        }


class TestUploadComplete:
    def test_complete_upload_sends_bucket_etag_size(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/objects/12/upload/complete",
            json={"data": {"id": 12}, "error": None},
        )
        client = StellarBridgeClient()
        client.complete_upload(12, bucket="b", etag="e", size_bytes=3)

        req = httpx_mock.get_requests()[0]
        body = json.loads(req.content.decode("utf-8"))
        assert body == {"bucket": "b", "etag": "e", "size_bytes": 3}


class TestGetAuditLogs:
    def test_empty_body_returns_empty_list(self, httpx_mock: pytest_httpx.HTTPXMock):
        """GET /logs must deserialize to a JSON array; empty HTTP body becomes []."""
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/logs?fileName=no-such-file.txt",
            status_code=200,
            content=b"",
        )
        client = StellarBridgeClient()
        assert client.get_audit_logs(fileName="no-such-file.txt") == []


class TestGetTransferPublicInfo:
    """GET /public/download/info uses X-API-Key like other /api/v1 routes."""

    def test_sends_x_api_key_and_unwraps_data_envelope(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/public/download/info/tid-public",
            json={
                "data": {"filename": "report.pdf", "size": 1024},
                "error": None,
            },
        )
        client = StellarBridgeClient()
        result = client.get_transfer_public_info("tid-public")
        assert result["filename"] == "report.pdf"
        assert result["size"] == 1024

        req = httpx_mock.get_requests()[0]
        assert req.headers.get("X-API-Key") == "test-api-key"


class TestMultipartTransferRoutes:
    def test_multipart_routes_are_relative_to_api_v1(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/bridge/uploads/initialize-multipart-upload",
            json={"fileId": "up-1", "fileKey": "key"},
        )
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/bridge/uploads/get-multipart-presigned-urls",
            json={"parts": []},
        )
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/bridge/uploads/finalize-multipart-upload",
            json={"transferId": "tid-1"},
        )
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/bridge/uploads/cancel",
            json={"ok": True},
        )

        client = StellarBridgeClient()
        client.initialize_multipart_upload({"name": "big.zip", "size": 100})
        client.get_multipart_presigned_urls({"fileId": "up-1", "fileKey": "key", "parts": 1})
        client.finalize_multipart_upload(
            {
                "fileId": "up-1",
                "fileKey": "key",
                "parts": [{"PartNumber": 1, "ETag": "etag"}],
                "size": 100,
            }
        )
        client.cancel_multipart_upload({"fileId": "up-1", "fileKey": "key"})

        multipart_requests = [
            req
            for req in httpx_mock.get_requests()
            if req.url.path.startswith("/api/v1/bridge/uploads/")
        ]
        assert len(multipart_requests) == 4


def test_get_client_singleton(monkeypatch: pytest.MonkeyPatch):
    """get_client returns the same instance across calls."""
    import stellarbridge_mcp.client as client_module

    monkeypatch.setattr(client_module, "_client", None)
    c1 = client_module.get_client()
    c2 = client_module.get_client()
    assert c1 is c2
