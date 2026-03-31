"""Tests for Drive MCP tools."""

import pytest
from unittest.mock import MagicMock, patch

import stellarbridge_mcp.tools.drive as drive_module
from stellarbridge_mcp.tools.drive import (
    list_drive_objects,
    get_drive_object,
    create_drive_folder,
    create_drive_file_placeholder,
    rename_drive_object,
    move_drive_object,
    delete_drive_object,
    get_drive_upload_url,
    complete_drive_upload,
    upload_drive_file_from_path,
    get_drive_download_url,
    share_drive_object,
    list_object_policy_attachments,
)


@pytest.fixture()
def mock_client():
    client = MagicMock()
    with patch.object(drive_module, "get_client", return_value=client):
        yield client


class TestListDriveObjects:
    def test_lists_root_objects(self, mock_client):
        mock_client.list_objects.return_value = [{"id": 1, "name": "folder", "type": "FOLDER"}]
        result = list_drive_objects(project_id=42)
        mock_client.list_objects.assert_called_once_with(42, None)
        assert result[0]["name"] == "folder"

    def test_lists_children_of_parent(self, mock_client):
        mock_client.list_objects.return_value = []
        list_drive_objects(project_id=42, parent_id=10)
        mock_client.list_objects.assert_called_once_with(42, 10)


class TestGetDriveObject:
    def test_returns_object_metadata(self, mock_client):
        mock_client.get_object.return_value = {"id": 5, "name": "report.pdf", "type": "FILE"}
        result = get_drive_object(object_id=5)
        mock_client.get_object.assert_called_once_with(5)
        assert result["type"] == "FILE"


class TestCreateDriveFolder:
    def test_creates_folder_at_root(self, mock_client):
        mock_client.create_object.return_value = {"id": 99, "type": "FOLDER", "name": "docs"}
        result = create_drive_folder(project_id=1, name="docs")
        mock_client.create_object.assert_called_once_with(
            {"type": "FOLDER", "project_id": 1, "name": "docs"}
        )
        assert result["id"] == 99

    def test_creates_folder_with_parent(self, mock_client):
        mock_client.create_object.return_value = {"id": 100}
        create_drive_folder(project_id=1, name="sub", parent_id=50)
        mock_client.create_object.assert_called_once_with(
            {"type": "FOLDER", "project_id": 1, "name": "sub", "parent_id": 50}
        )


class TestCreateDriveFilePlaceholder:
    def test_creates_file_placeholder(self, mock_client):
        mock_client.create_object.return_value = {"id": 7, "type": "FILE"}
        create_drive_file_placeholder(
            project_id=1, name="data.csv", mime_type="text/csv"
        )
        mock_client.create_object.assert_called_once_with(
            {"type": "FILE", "project_id": 1, "name": "data.csv", "mime_type": "text/csv"}
        )

    def test_creates_file_with_parent(self, mock_client):
        mock_client.create_object.return_value = {"id": 8}
        create_drive_file_placeholder(
            project_id=1, name="img.png", mime_type="image/png", parent_id=3
        )
        call_payload = mock_client.create_object.call_args[0][0]
        assert call_payload["parent_id"] == 3


class TestRenameAndMoveDriveObject:
    def test_rename(self, mock_client):
        mock_client.update_object.return_value = {"id": 5, "name": "new.pdf"}
        rename_drive_object(object_id=5, new_name="new.pdf")
        mock_client.update_object.assert_called_once_with(5, {"name": "new.pdf"})

    def test_move(self, mock_client):
        mock_client.update_object.return_value = {"id": 5}
        move_drive_object(object_id=5, new_parent_id=20)
        mock_client.update_object.assert_called_once_with(5, {"parent_id": 20})

    def test_move_to_root_by_omitting_parent(self, mock_client):
        mock_client.update_object.return_value = {"id": 5}
        move_drive_object(object_id=5)
        mock_client.update_object.assert_called_once_with(5, {"parent_id": 0})

    def test_move_to_root_with_explicit_zero(self, mock_client):
        mock_client.update_object.return_value = {"id": 5}
        move_drive_object(object_id=5, new_parent_id=0)
        mock_client.update_object.assert_called_once_with(5, {"parent_id": 0})

class TestDeleteDriveObject:
    def test_deletes_object(self, mock_client):
        mock_client.delete_object.return_value = None
        delete_drive_object(object_id=5)
        mock_client.delete_object.assert_called_once_with(5)


class TestUploadDownload:
    def test_get_upload_url(self, mock_client):
        mock_client.get_upload_url.return_value = {"url": "https://s3.example.com/put"}
        result = get_drive_upload_url(object_id=5)
        assert "url" in result

    def test_complete_upload(self, mock_client):
        mock_client.complete_upload.return_value = {"status": "ok"}
        complete_drive_upload(
            object_id=5,
            bucket="bucket-1",
            etag="etag-1",
            size_bytes=123,
        )
        mock_client.complete_upload.assert_called_once_with(5, "bucket-1", "etag-1", 123)

    def test_upload_drive_file_from_path_puts_bytes_and_completes(self, mock_client, tmp_path, monkeypatch):
        p = tmp_path / "test.txt"
        p.write_text("hello")

        mock_client.get_upload_url.return_value = {
            "data": {
                "bucket": "bkt",
                "upload_url": "https://storage.example.com/put",
            },
            "error": None,
        }

        class DummyResp:
            status_code = 200
            headers = {"ETag": '"etag-123"'}

            def raise_for_status(self):
                return None

        class DummyHttpClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def put(self, url, *, content=None, headers=None):
                assert url == "https://storage.example.com/put"
                assert headers == {"Content-Type": "text/plain"}
                # Ensure content is a readable stream (file handle).
                assert hasattr(content, "read")
                assert content.read() == b"hello"
                return DummyResp()

        monkeypatch.setattr(drive_module.httpx, "Client", DummyHttpClient)

        mock_client.complete_upload.return_value = {"ok": True}

        result = upload_drive_file_from_path(
            object_id=5,
            file_path=str(p),
            content_type="text/plain",
        )

        mock_client.get_upload_url.assert_called_once_with(5)
        mock_client.complete_upload.assert_called_once_with(5, "bkt", "etag-123", 5)
        assert result["object_id"] == 5
        assert result["size_bytes"] == 5

    def test_get_download_url(self, mock_client):
        mock_client.get_download_url.return_value = {"url": "https://s3.example.com/get"}
        result = get_drive_download_url(object_id=5)
        assert "url" in result


class TestShareDriveObject:
    def test_shares_with_recipient(self, mock_client):
        mock_client.share_object.return_value = {"shareToken": "abc123"}
        share_drive_object(object_id=5, recipient_email="user@example.com")
        mock_client.share_object.assert_called_once_with(5, "user@example.com")


class TestPolicyAttachments:
    def test_list_attachments(self, mock_client):
        mock_client.list_policy_attachments.return_value = []
        list_object_policy_attachments(object_id=5)
        mock_client.list_policy_attachments.assert_called_once_with(5)
