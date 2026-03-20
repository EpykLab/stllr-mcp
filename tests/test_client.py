"""Tests for the StellarBridgeClient."""

import pytest
import httpx
import pytest_httpx

from stellarbridge_mcp.client import StellarBridgeClient
from stellarbridge_mcp import config


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch):
    """Reset settings to known values for each test."""
    monkeypatch.setattr(config.settings, "api_url", "http://localhost:8080")
    monkeypatch.setattr(config.settings, "api_key", "test-api-key")
    monkeypatch.setattr(config.settings, "jwt_token", "")
    monkeypatch.setattr(config.settings, "http_timeout", 5.0)


class TestAuthentication:
    def test_authenticate_stores_token(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/auth",
            json={"token": "jwt-abc"},
        )
        client = StellarBridgeClient()
        token = client.authenticate("my-api-key")
        assert token == "jwt-abc"
        assert client._token == "jwt-abc"

    def test_lazy_auth_on_first_request(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/auth",
            json={"token": "jwt-lazy"},
        )
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/objects?project_id=1",
            json=[],
        )
        client = StellarBridgeClient()
        client.list_objects(1)
        assert client._token == "jwt-lazy"

    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.setattr(config.settings, "api_key", "")
        client = StellarBridgeClient()
        with pytest.raises(RuntimeError, match="No API key configured"):
            client._authenticate()

    def test_retries_on_401(self, httpx_mock: pytest_httpx.HTTPXMock):
        # First GET returns 401, then re-auth, then success
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/auth",
            json={"token": "jwt-initial"},
        )
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/objects?project_id=1",
            status_code=401,
        )
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/auth",
            json={"token": "jwt-refreshed"},
        )
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/objects?project_id=1",
            json=[{"id": 1}],
        )
        client = StellarBridgeClient()
        result = client.list_objects(1)
        assert result == [{"id": 1}]
        assert client._token == "jwt-refreshed"


class TestListObjects:
    def test_without_parent(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/auth",
            json={"token": "tok"},
        )
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/objects?project_id=5",
            json=[{"id": 10, "name": "root"}],
        )
        client = StellarBridgeClient()
        result = client.list_objects(5)
        assert result[0]["name"] == "root"

    def test_params_omit_none(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Request params with None values are omitted from the query string."""
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/auth",
            json={"token": "tok"},
        )
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/objects?project_id=5",
            json=[],
        )
        client = StellarBridgeClient()
        client.list_objects(5)
        # Only project_id=5 should appear; parent_id must not be sent
        requests = [r for r in httpx_mock.get_requests() if r.url.path == "/api/v1/objects"]
        assert len(requests) == 1
        assert "parent_id" not in str(requests[0].url)


class TestBaseUrl:
    def test_trailing_slash_stripped(self, monkeypatch, httpx_mock: pytest_httpx.HTTPXMock):
        monkeypatch.setattr(config.settings, "api_url", "http://localhost:8080/")
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/auth",
            json={"token": "t"},
        )
        client = StellarBridgeClient()
        client.authenticate("key")
        # Auth URL should be normalised (no double slash before api/v1)
        requests = [r for r in httpx_mock.get_requests() if "auth" in r.url.path]
        assert len(requests) == 1
        assert requests[0].url == "http://localhost:8080/api/v1/auth"


class TestRequestBehavior:
    def test_raises_on_4xx(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/auth",
            json={"token": "t"},
        )
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/objects/999",
            status_code=404,
        )
        client = StellarBridgeClient()
        with pytest.raises(httpx.HTTPStatusError):
            client.get_object(999)

    def test_returns_none_for_empty_response(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/auth",
            json={"token": "t"},
        )
        httpx_mock.add_response(
            method="DELETE",
            url="http://localhost:8080/api/v1/objects/1",
            status_code=200,
            content=b"",
        )
        client = StellarBridgeClient()
        result = client.delete_object(1)
        assert result is None


class TestGetTransferPublicInfo:
    """Public info endpoint uses unauthenticated GET."""

    def test_returns_public_info_without_auth(self, httpx_mock: pytest_httpx.HTTPXMock):
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:8080/api/v1/public/download/info/tid-public",
            json={"fileName": "report.pdf", "sizeBytes": 1024},
        )
        client = StellarBridgeClient()
        result = client.get_transfer_public_info("tid-public")
        assert result["fileName"] == "report.pdf"
        assert result["sizeBytes"] == 1024
        requests = httpx_mock.get_requests()
        assert len(requests) == 1
        assert "Authorization" not in requests[0].headers


class TestMultipartTransferRoutes:
    def test_multipart_routes_are_relative_to_api_v1(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:8080/api/v1/auth",
            json={"token": "tok"},
        )
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


def test_get_client_singleton(monkeypatch):
    """get_client returns the same instance across calls."""
    import stellarbridge_mcp.client as client_module

    monkeypatch.setattr(client_module, "_client", None)
    c1 = client_module.get_client()
    c2 = client_module.get_client()
    assert c1 is c2
