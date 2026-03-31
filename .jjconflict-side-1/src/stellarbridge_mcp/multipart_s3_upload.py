"""Upload local file parts to S3 using presigned PUT URLs from multipart transfer APIs."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .client import StellarBridgeClient

# S3 multipart: each part except the last must be at least 5 MiB.
MIN_PART_SIZE_BYTES = 5 * 1024 * 1024
DEFAULT_PART_SIZE_BYTES = 8 * 1024 * 1024


def resolve_upload_ids(init_response: dict[str, Any]) -> tuple[str, str]:
    """Extract file id and object key from initialize-multipart-upload response."""
    file_id = (
        init_response.get("fileId")
        or init_response.get("uploadId")
        or init_response.get("file_id")
    )
    file_key = init_response.get("fileKey") or init_response.get("file_key")
    if not file_id or not file_key:
        raise ValueError(
            "initialize_multipart_upload response must include fileId (or uploadId) and fileKey; "
            f"got keys: {list(init_response.keys())}"
        )
    return str(file_id), str(file_key)


def normalize_presigned_urls_response(response: dict[str, Any]) -> list[tuple[int, str]]:
    """Parse get-multipart-presigned-urls JSON into sorted (part number, presigned URL) pairs."""
    raw_parts = response.get("parts")
    if isinstance(raw_parts, list) and raw_parts:
        out: list[tuple[int, str]] = []
        for item in raw_parts:
            if not isinstance(item, dict):
                raise ValueError(f"Each parts[] entry must be an object, got {type(item).__name__}")
            url = item.get("url") or item.get("presignedUrl") or item.get("signedUrl")
            pn = item.get("partNumber") or item.get("PartNumber")
            if not url or pn is None:
                raise ValueError(f"Each part needs url and partNumber/PartNumber: {item!r}")
            out.append((int(pn), str(url)))
        if not out:
            raise ValueError("parts list is empty")
        return sorted(out, key=lambda x: x[0])

    raw_urls = response.get("urls")
    if isinstance(raw_urls, list) and raw_urls:
        out = []
        for i, u in enumerate(raw_urls):
            if isinstance(u, str):
                out.append((i + 1, u))
            elif isinstance(u, dict):
                url = u.get("url") or u.get("presignedUrl") or u.get("signedUrl")
                pn = u.get("partNumber") or u.get("PartNumber")
                if not url:
                    raise ValueError(f"urls[] entry missing url: {u!r}")
                out.append((int(pn) if pn is not None else i + 1, str(url)))
            else:
                raise ValueError(f"Unsupported urls[] entry type: {type(u).__name__}")
        if not out:
            raise ValueError("urls list is empty")
        return sorted(out, key=lambda x: x[0])

    raise ValueError(
        "Unsupported presigned URL response: expected non-empty 'parts' or 'urls'. "
        f"Keys present: {list(response.keys())}"
    )


def strip_s3_etag(etag: str) -> str:
    """Normalize ETag from S3 PUT response headers (strip quotes)."""
    return etag.strip().strip('"')


def part_count_for_size(total_size: int, part_size_bytes: int) -> int:
    """Number of multipart parts for a file of total_size using fixed part_size_bytes."""
    if total_size < 0:
        raise ValueError("total_size must be non-negative")
    if part_size_bytes < MIN_PART_SIZE_BYTES:
        raise ValueError(
            f"part_size_bytes must be >= {MIN_PART_SIZE_BYTES} (S3 multipart minimum)"
        )
    if total_size == 0:
        return 1
    return max(1, math.ceil(total_size / part_size_bytes))


def byte_ranges_for_parts(
    total_size: int, part_size_bytes: int, num_parts: int
) -> list[tuple[int, int]]:
    """Return (offset, length) for each part in sequential order."""
    if num_parts < 1:
        raise ValueError("num_parts must be >= 1")
    ranges: list[tuple[int, int]] = []
    offset = 0
    for _ in range(num_parts):
        remaining = total_size - offset
        if remaining <= 0:
            length = 0
        else:
            length = min(part_size_bytes, remaining)
        ranges.append((offset, length))
        offset += length
    return ranges


def put_multipart_parts_to_s3(
    presigned_entries: list[tuple[int, str]],
    file_path: Path,
    total_size: int,
    part_size_bytes: int,
    *,
    timeout: float,
) -> list[dict[str, Any]]:
    """HTTP PUT each file segment to its presigned URL; return finalize payload parts."""
    sorted_entries = sorted(presigned_entries, key=lambda x: x[0])
    num_parts = len(sorted_entries)
    ranges = byte_ranges_for_parts(total_size, part_size_bytes, num_parts)
    if len(ranges) != num_parts:
        raise ValueError("internal error: range list length mismatch")

    result: list[dict[str, Any]] = []
    with httpx.Client(timeout=timeout) as http_client:
        with Path(file_path).open("rb") as f:
            for (part_number, url), (start, length) in zip(sorted_entries, ranges, strict=True):
                f.seek(start)
                chunk = f.read(length) if length > 0 else b""
                resp = http_client.put(url, content=chunk)
                resp.raise_for_status()
                etag_header = resp.headers.get("ETag") or resp.headers.get("etag")
                if not etag_header:
                    raise RuntimeError(
                        f"S3 PUT for part {part_number} returned no ETag header "
                        f"(status {resp.status_code})"
                    )
                result.append(
                    {"PartNumber": part_number, "ETag": strip_s3_etag(etag_header)}
                )
    return result


def run_transfer_multipart_upload(
    client: StellarBridgeClient,
    file_path: str | Path,
    *,
    file_name: str | None = None,
    part_size_bytes: int = DEFAULT_PART_SIZE_BYTES,
    http_timeout: float,
) -> Any:
    """End-to-end: initialize multipart transfer, PUT all parts to S3, finalize."""
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"not a file: {path}")

    total_size = path.stat().st_size
    display_name = file_name if file_name is not None else path.name

    init = client.initialize_multipart_upload({"name": display_name, "size": total_size})
    if not isinstance(init, dict):
        raise TypeError(f"initialize_multipart_upload returned {type(init).__name__}, expected dict")

    file_id, file_key = resolve_upload_ids(init)
    n_parts = part_count_for_size(total_size, part_size_bytes)

    urls_resp = client.get_multipart_presigned_urls(
        {"fileId": file_id, "fileKey": file_key, "parts": n_parts}
    )
    if not isinstance(urls_resp, dict):
        raise TypeError(
            f"get_multipart_presigned_urls returned {type(urls_resp).__name__}, expected dict"
        )

    entries = normalize_presigned_urls_response(urls_resp)
    if len(entries) != n_parts:
        raise RuntimeError(
            f"Expected {n_parts} presigned URLs, got {len(entries)} "
            f"(check API response parts/urls)"
        )

    completed = put_multipart_parts_to_s3(
        entries, path, total_size, part_size_bytes, timeout=http_timeout
    )

    return client.finalize_multipart_upload(
        {
            "fileId": file_id,
            "fileKey": file_key,
            "parts": completed,
            "size": total_size,
        }
    )
