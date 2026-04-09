"""Tests for multipart S3 PUT upload helpers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stellarbridge_mcp.multipart_s3_upload import (
    DEFAULT_PART_SIZE_BYTES,
    MIN_PART_SIZE_BYTES,
    byte_ranges_for_parts,
    normalize_presigned_urls_response,
    part_count_for_size,
    put_multipart_parts_to_s3,
    resolve_upload_ids,
    run_transfer_multipart_upload,
    strip_s3_etag,
)


class TestResolveUploadIds:
    def test_file_id_and_file_key(self) -> None:
        fid, fk = resolve_upload_ids({"fileId": "a", "fileKey": "k"})
        assert fid == "a" and fk == "k"

    def test_upload_id_alias(self) -> None:
        fid, fk = resolve_upload_ids({"uploadId": "b", "fileKey": "k2"})
        assert fid == "b" and fk == "k2"

    def test_raises_when_missing(self) -> None:
        with pytest.raises(ValueError, match="fileId"):
            resolve_upload_ids({"fileKey": "k"})


class TestNormalizePresignedUrlsResponse:
    def test_parts_with_part_number(self) -> None:
        r = normalize_presigned_urls_response(
            {
                "parts": [
                    {"partNumber": 2, "url": "https://u2"},
                    {"partNumber": 1, "url": "https://u1"},
                ]
            }
        )
        assert r == [(1, "https://u1"), (2, "https://u2")]

    def test_parts_pascal_case(self) -> None:
        r = normalize_presigned_urls_response(
            {"parts": [{"PartNumber": 1, "url": "https://x"}]}
        )
        assert r == [(1, "https://x")]

    def test_urls_strings(self) -> None:
        r = normalize_presigned_urls_response({"urls": ["https://a", "https://b"]})
        assert r == [(1, "https://a"), (2, "https://b")]

    def test_urls_objects(self) -> None:
        r = normalize_presigned_urls_response(
            {"urls": [{"url": "https://a", "partNumber": 1}]}
        )
        assert r == [(1, "https://a")]


class TestPartCount:
    def test_zero_bytes(self) -> None:
        assert part_count_for_size(0, MIN_PART_SIZE_BYTES) == 1

    def test_single_part_small_file(self) -> None:
        assert part_count_for_size(1024, DEFAULT_PART_SIZE_BYTES) == 1

    def test_multi_part(self) -> None:
        assert part_count_for_size(10 * MIN_PART_SIZE_BYTES, MIN_PART_SIZE_BYTES) == 10

    def test_rejects_small_part_size(self) -> None:
        with pytest.raises(ValueError, match="5242880"):
            part_count_for_size(100, MIN_PART_SIZE_BYTES - 1)


class TestByteRanges:
    def test_two_parts(self) -> None:
        ps = MIN_PART_SIZE_BYTES
        r = byte_ranges_for_parts(ps + 100, ps, 2)
        assert r == [(0, ps), (ps, 100)]


class TestStripEtag:
    def test_strips_quotes(self) -> None:
        assert strip_s3_etag('"abc"') == "abc"


class TestPutMultipartPartsToS3:
    def test_puts_each_range(self, tmp_path: Path) -> None:
        p = tmp_path / "f.bin"
        p.write_bytes(b"abcdefghij")
        entries = [(1, "https://s3/p1"), (2, "https://s3/p2")]
        with patch("stellarbridge_mcp.multipart_s3_upload.httpx.Client") as C:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {"ETag": '"e1"'}
            mock_resp.raise_for_status = MagicMock()
            mock_client = MagicMock()
            mock_client.put.return_value = mock_resp
            ctx = MagicMock()
            ctx.__enter__.return_value = mock_client
            ctx.__exit__.return_value = None
            C.return_value = ctx

            out = put_multipart_parts_to_s3(
                entries, p, total_size=10, part_size_bytes=5, timeout=30.0
            )

            assert len(out) == 2
            assert mock_client.put.call_count == 2
            assert mock_client.put.call_args_list[0][0][0] == "https://s3/p1"
            assert mock_client.put.call_args_list[0][1]["content"] == b"abcde"
            assert mock_client.put.call_args_list[1][1]["content"] == b"fghij"
            assert out[0]["PartNumber"] == 1
            assert out[1]["PartNumber"] == 2


class TestRunTransferMultipartUpload:
    def test_end_to_end(self, tmp_path: Path) -> None:
        f = tmp_path / "up.bin"
        f.write_bytes(b"x" * 100)

        client = MagicMock()
        client.initialize_multipart_upload.return_value = {
            "fileId": "fid",
            "fileKey": "fkey",
        }
        client.get_multipart_presigned_urls.return_value = {
            "parts": [{"partNumber": 1, "url": "https://s3/put"}],
        }
        client.finalize_multipart_upload.return_value = {"transferId": "tid"}

        with patch(
            "stellarbridge_mcp.multipart_s3_upload.put_multipart_parts_to_s3"
        ) as put:
            put.return_value = [{"PartNumber": 1, "ETag": "e"}]

            result = run_transfer_multipart_upload(
                client,
                f,
                file_name="n.bin",
                part_size_bytes=MIN_PART_SIZE_BYTES,
                http_timeout=5.0,
            )

        assert result == {"transferId": "tid"}
        client.initialize_multipart_upload.assert_called_once()
        init_payload = client.initialize_multipart_upload.call_args[0][0]
        assert init_payload["name"] == "n.bin"
        assert init_payload["size"] == 100
        client.get_multipart_presigned_urls.assert_called_once()
        client.finalize_multipart_upload.assert_called_once()

    def test_resolves_tid_from_list_transfers_when_finalize_omits_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Avoid real sleeping in tests.
        monkeypatch.setattr("time.sleep", lambda _s: None)

        f = tmp_path / "up.bin"
        f.write_bytes(b"x" * 100)

        client = MagicMock()
        client.initialize_multipart_upload.return_value = {
            "fileId": "fid",
            "fileKey": "fkey",
        }
        client.get_multipart_presigned_urls.return_value = {
            "parts": [{"partNumber": 1, "url": "https://s3/put"}],
        }
        # Backend sometimes returns a message only, without tid.
        client.finalize_multipart_upload.return_value = {"data": {"message": "object uploaded"}}
        client.list_transfers.return_value = [
            {
                "name": "n.bin",
                "size": 100,
                "createdAt": "2099-01-01T00:00:00Z",
                "tid": "tid-from-list",
            }
        ]

        with patch(
            "stellarbridge_mcp.multipart_s3_upload.put_multipart_parts_to_s3"
        ) as put:
            put.return_value = [{"PartNumber": 1, "ETag": "e"}]

            result = run_transfer_multipart_upload(
                client,
                f,
                file_name="n.bin",
                part_size_bytes=MIN_PART_SIZE_BYTES,
                http_timeout=5.0,
            )

        assert result["transferId"] == "tid-from-list"
        client.list_transfers.assert_called()
