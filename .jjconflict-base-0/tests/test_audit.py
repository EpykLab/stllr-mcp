"""Tests for audit log MCP tools."""

import pytest
from unittest.mock import MagicMock, patch

import stellarbridge_mcp.tools.audit as audit_module
from stellarbridge_mcp.tools.audit import (
    get_audit_logs,
    get_audit_logs_for_actor,
    get_audit_logs_for_file,
)


@pytest.fixture()
def mock_client():
    client = MagicMock()
    with patch.object(audit_module, "get_client", return_value=client):
        yield client


class TestGetAuditLogs:
    def test_no_filters(self, mock_client):
        mock_client.get_audit_logs.return_value = []
        get_audit_logs()
        mock_client.get_audit_logs.assert_called_once_with()

    def test_with_time_range(self, mock_client):
        mock_client.get_audit_logs.return_value = []
        get_audit_logs(start_time="2025-01-01T00:00:00Z", end_time="2025-01-31T23:59:59Z")
        kwargs = mock_client.get_audit_logs.call_args[1]
        assert kwargs["startTime"] == "2025-01-01T00:00:00Z"
        assert kwargs["endTime"] == "2025-01-31T23:59:59Z"

    def test_with_actor_filter(self, mock_client):
        mock_client.get_audit_logs.return_value = []
        get_audit_logs(actor="user-42")
        kwargs = mock_client.get_audit_logs.call_args[1]
        assert kwargs["actor"] == "user-42"

    def test_limit_clamped_to_1000(self, mock_client):
        mock_client.get_audit_logs.return_value = []
        get_audit_logs(limit=9999)
        kwargs = mock_client.get_audit_logs.call_args[1]
        assert kwargs["limit"] == 1000

    def test_limit_clamped_to_1(self, mock_client):
        mock_client.get_audit_logs.return_value = []
        get_audit_logs(limit=0)
        kwargs = mock_client.get_audit_logs.call_args[1]
        assert kwargs["limit"] == 1

    def test_all_filters(self, mock_client):
        mock_client.get_audit_logs.return_value = []
        get_audit_logs(
            start_time="2025-01-01T00:00:00Z",
            end_time="2025-01-31T23:59:59Z",
            actor="user-1",
            file_name="report.pdf",
            file_hash="abc123",
            org_id="org-1",
            user_id="uid-1",
            limit=100,
        )
        kwargs = mock_client.get_audit_logs.call_args[1]
        assert kwargs["fileName"] == "report.pdf"
        assert kwargs["fileHash"] == "abc123"
        assert kwargs["orgId"] == "org-1"
        assert kwargs["userId"] == "uid-1"


class TestGetAuditLogsForActor:
    def test_filters_by_actor(self, mock_client):
        mock_client.get_audit_logs.return_value = [{"actor": "user-5"}]
        get_audit_logs_for_actor(actor_id="user-5")
        kwargs = mock_client.get_audit_logs.call_args[1]
        assert kwargs["actor"] == "user-5"

    def test_with_time_range_and_limit(self, mock_client):
        mock_client.get_audit_logs.return_value = []
        get_audit_logs_for_actor(
            actor_id="agent-1",
            start_time="2025-06-01T00:00:00Z",
            end_time="2025-06-30T23:59:59Z",
            limit=50,
        )
        kwargs = mock_client.get_audit_logs.call_args[1]
        assert kwargs["startTime"] == "2025-06-01T00:00:00Z"
        assert kwargs["limit"] == 50


class TestGetAuditLogsForFile:
    def test_requires_at_least_one_param(self, mock_client):
        with pytest.raises(ValueError):
            get_audit_logs_for_file()

    def test_filters_by_file_name(self, mock_client):
        mock_client.get_audit_logs.return_value = []
        get_audit_logs_for_file(file_name="contract.pdf")
        kwargs = mock_client.get_audit_logs.call_args[1]
        assert kwargs["fileName"] == "contract.pdf"

    def test_filters_by_file_hash(self, mock_client):
        mock_client.get_audit_logs.return_value = []
        get_audit_logs_for_file(file_hash="deadbeef")
        kwargs = mock_client.get_audit_logs.call_args[1]
        assert kwargs["fileHash"] == "deadbeef"

    def test_filters_by_both(self, mock_client):
        mock_client.get_audit_logs.return_value = []
        get_audit_logs_for_file(file_name="report.pdf", file_hash="abc123")
        kwargs = mock_client.get_audit_logs.call_args[1]
        assert "fileName" in kwargs
        assert "fileHash" in kwargs
