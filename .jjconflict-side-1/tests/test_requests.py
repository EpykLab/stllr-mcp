"""Tests for file request MCP tools."""

import pytest
from unittest.mock import MagicMock, patch

import stellarbridge_mcp.tools.requests as requests_module
from stellarbridge_mcp.tools.requests import (
    create_file_request,
    get_file_request,
    delete_file_request,
)


@pytest.fixture()
def mock_client():
    client = MagicMock()
    with patch.object(requests_module, "get_client", return_value=client):
        yield client


class TestCreateFileRequest:
    def test_creates_minimal_request(self, mock_client):
        mock_client.create_file_request.return_value = {"id": "req-1"}
        create_file_request(title="Please upload Q4 report", recipient_email="finance@corp.com")
        payload = mock_client.create_file_request.call_args[0][0]
        assert payload["title"] == "Please upload Q4 report"
        assert payload["recipientEmail"] == "finance@corp.com"
        assert "message" not in payload
        assert "projectId" not in payload

    def test_creates_request_with_all_fields(self, mock_client):
        mock_client.create_file_request.return_value = {"id": "req-2"}
        create_file_request(
            title="Upload contract",
            recipient_email="vendor@example.com",
            message="Please upload the signed contract.",
            expiry_hours=72,
            project_id=5,
            parent_id=10,
        )
        payload = mock_client.create_file_request.call_args[0][0]
        assert payload["message"] == "Please upload the signed contract."
        assert payload["expiryHours"] == 72
        assert payload["projectId"] == 5
        assert payload["parentId"] == 10


class TestGetFileRequest:
    def test_returns_request(self, mock_client):
        mock_client.get_file_request.return_value = {"id": "req-1", "status": "pending"}
        result = get_file_request(request_id="req-1")
        assert result["status"] == "pending"
        mock_client.get_file_request.assert_called_once_with("req-1")


class TestDeleteFileRequest:
    def test_deletes_request(self, mock_client):
        mock_client.delete_file_request.return_value = None
        delete_file_request(request_id="req-1")
        mock_client.delete_file_request.assert_called_once_with("req-1")
