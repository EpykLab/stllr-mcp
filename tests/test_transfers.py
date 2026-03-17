"""Tests for Transfer MCP tools."""

import pytest
from unittest.mock import MagicMock, patch

import stellarbridge_mcp.tools.transfers as transfers_module
from stellarbridge_mcp.tools.transfers import (
    list_transfers,
    get_transfer,
    delete_transfer,
    share_transfer,
    add_transfer_to_drive,
    get_transfer_public_info,
    initialize_multipart_upload,
    get_multipart_presigned_urls,
    finalize_multipart_upload,
    cancel_multipart_upload,
)


@pytest.fixture()
def mock_client():
    client = MagicMock()
    with patch.object(transfers_module, "get_client", return_value=client):
        yield client


class TestListTransfers:
    def test_lists_all(self, mock_client):
        mock_client.list_transfers.return_value = []
        list_transfers()
        mock_client.list_transfers.assert_called_once_with(None)

    def test_filters_by_org(self, mock_client):
        mock_client.list_transfers.return_value = []
        list_transfers(org_id="org-123")
        mock_client.list_transfers.assert_called_once_with("org-123")


class TestGetTransfer:
    def test_returns_transfer(self, mock_client):
        mock_client.get_transfer.return_value = {"id": "tid-1", "sizeBytes": 1024}
        result = get_transfer(transfer_id="tid-1")
        assert result["id"] == "tid-1"


class TestDeleteTransfer:
    def test_deletes(self, mock_client):
        mock_client.delete_transfer.return_value = None
        delete_transfer(transfer_id="tid-1")
        mock_client.delete_transfer.assert_called_once_with("tid-1")


class TestShareTransfer:
    def test_shares_with_email(self, mock_client):
        mock_client.share_transfer.return_value = {"status": "sent"}
        share_transfer(transfer_id="tid-1", recipient_email="bob@example.com")
        mock_client.share_transfer.assert_called_once_with("tid-1", "bob@example.com")


class TestAddTransferToDrive:
    def test_adds_to_project_root(self, mock_client):
        mock_client.add_transfer_to_drive.return_value = {"objectId": 50}
        add_transfer_to_drive(transfer_id="tid-1", project_id=10)
        mock_client.add_transfer_to_drive.assert_called_once_with("tid-1", 10, None)

    def test_adds_to_folder(self, mock_client):
        mock_client.add_transfer_to_drive.return_value = {"objectId": 51}
        add_transfer_to_drive(transfer_id="tid-1", project_id=10, parent_id=30)
        mock_client.add_transfer_to_drive.assert_called_once_with("tid-1", 10, 30)


class TestGetTransferPublicInfo:
    def test_returns_public_info(self, mock_client):
        mock_client.get_transfer_public_info.return_value = {"fileName": "doc.pdf"}
        result = get_transfer_public_info(transfer_id="tid-public")
        assert result["fileName"] == "doc.pdf"


class TestMultipartUpload:
    def test_initialize(self, mock_client):
        mock_client.initialize_multipart_upload.return_value = {"uploadId": "up-1"}
        result = initialize_multipart_upload(
            file_name="big.zip", mime_type="application/zip", size_bytes=50_000_000
        )
        assert result["uploadId"] == "up-1"
        called_payload = mock_client.initialize_multipart_upload.call_args[0][0]
        assert called_payload["fileName"] == "big.zip"
        assert "expiryHours" not in called_payload

    def test_initialize_with_expiry(self, mock_client):
        mock_client.initialize_multipart_upload.return_value = {}
        initialize_multipart_upload(
            file_name="f.bin", mime_type="application/octet-stream",
            size_bytes=100, expiry_hours=48
        )
        payload = mock_client.initialize_multipart_upload.call_args[0][0]
        assert payload["expiryHours"] == 48

    def test_get_presigned_urls(self, mock_client):
        mock_client.get_multipart_presigned_urls.return_value = {"urls": []}
        get_multipart_presigned_urls(
            upload_id="up-1", s3_key="key", s3_bucket="bucket", part_numbers=[1, 2]
        )
        payload = mock_client.get_multipart_presigned_urls.call_args[0][0]
        assert payload["partNumbers"] == [1, 2]

    def test_finalize(self, mock_client):
        mock_client.finalize_multipart_upload.return_value = {"transferId": "tid-1"}
        parts = [{"PartNumber": 1, "ETag": "etag1"}]
        finalize_multipart_upload(
            upload_id="up-1", s3_key="key", s3_bucket="bucket", parts=parts
        )
        payload = mock_client.finalize_multipart_upload.call_args[0][0]
        assert payload["parts"] == parts

    def test_cancel(self, mock_client):
        mock_client.cancel_multipart_upload.return_value = None
        cancel_multipart_upload(upload_id="up-1", s3_key="key", s3_bucket="bucket")
        mock_client.cancel_multipart_upload.assert_called_once()
