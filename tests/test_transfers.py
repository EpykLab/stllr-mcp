"""Tests for Transfer MCP tools."""

import pytest
from unittest.mock import MagicMock, patch

import stellarbridge_mcp.tools.transfers as transfers_module
from stellarbridge_mcp.multipart_s3_upload import DEFAULT_PART_SIZE_BYTES
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
    upload_transfer_multipart_file,
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
            file_name="big.zip", size_bytes=50_000_000
        )
        assert result["uploadId"] == "up-1"
        called_payload = mock_client.initialize_multipart_upload.call_args[0][0]
        assert called_payload["name"] == "big.zip"
        assert called_payload["size"] == 50_000_000

    def test_get_presigned_urls(self, mock_client):
        mock_client.get_multipart_presigned_urls.return_value = {"urls": []}
        get_multipart_presigned_urls(
            upload_id="up-1", file_key="key", parts=2
        )
        payload = mock_client.get_multipart_presigned_urls.call_args[0][0]
        assert payload["fileId"] == "up-1"
        assert payload["fileKey"] == "key"
        assert payload["parts"] == 2

    def test_finalize(self, mock_client):
        mock_client.finalize_multipart_upload.return_value = {"transferId": "tid-1"}
        parts = [{"PartNumber": 1, "ETag": "etag1"}]
        finalize_multipart_upload(
            upload_id="up-1", file_key="key", parts=parts, size_bytes=5_242_880
        )
        payload = mock_client.finalize_multipart_upload.call_args[0][0]
        assert payload["fileId"] == "up-1"
        assert payload["fileKey"] == "key"
        assert payload["parts"] == parts
        assert payload["size"] == 5_242_880

    def test_cancel(self, mock_client):
        mock_client.cancel_multipart_upload.return_value = None
        cancel_multipart_upload(upload_id="up-1", file_key="key")
        mock_client.cancel_multipart_upload.assert_called_once_with(
            {"fileId": "up-1", "fileKey": "key"}
        )


class TestUploadTransferMultipartFile:
    def test_delegates_to_runner(self, mock_client):
        with patch.object(
            transfers_module,
            "run_transfer_multipart_upload",
            return_value={"transferId": "tid-upload"},
        ) as run:
            result = upload_transfer_multipart_file(
                file_path="/tmp/local.bin",
                file_name="remote.bin",
                part_size_bytes=DEFAULT_PART_SIZE_BYTES,
            )
        assert result == {"transferId": "tid-upload"}
        run.assert_called_once()
        assert run.call_args[0][0] is mock_client
