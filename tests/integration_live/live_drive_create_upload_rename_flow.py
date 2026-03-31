#!/usr/bin/env python3
"""Live API: file placeholder at project root, upload bytes, then rename.

Drive listings omit unfinalized file placeholders; upload complete first so the
object matches production visibility (see ``ObjectListChildren`` in the API).

Run from repo root::

  STELLARBRIDGE_TEST_PROJECT_ID=7 PYTHONPATH=. uv run python \\
    tests/integration_live/live_drive_create_upload_rename_flow.py

Requires ``STELLARBRIDGE_API_URL`` and ``STELLARBRIDGE_API_KEY`` (e.g. via ``.env``).

For the parametrized stdio live test, also set ``STELLARBRIDGE_LIVE_ALLOW_MUTATIONS=1``
(see ``live_tool_registry``).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "tests/fixtures/uploads/multipart_upload.bin"


def _object_id(resp: object) -> int:
    if not isinstance(resp, dict):
        raise TypeError(f"expected dict, got {type(resp)}")
    data = resp.get("data")
    if isinstance(data, dict) and "id" in data:
        return int(data["id"])
    raise ValueError(f"cannot extract object id from: {resp!r}")


def main() -> int:
    os.chdir(_REPO)
    raw = os.environ.get("STELLARBRIDGE_TEST_PROJECT_ID", "").strip()
    if not raw:
        print("Set STELLARBRIDGE_TEST_PROJECT_ID", file=sys.stderr)
        return 1
    project_id = int(raw, 10)
    if not _FIXTURE.is_file():
        print(f"Missing fixture: {_FIXTURE}", file=sys.stderr)
        return 1

    from stellarbridge_mcp.tools.drive import (
        create_drive_file_placeholder,
        rename_drive_object,
        upload_drive_file_from_path,
    )

    file_name = f"live-upload-{uuid.uuid4().hex[:10]}.bin"
    new_name = f"live-renamed-{uuid.uuid4().hex[:10]}.bin"

    print("1. create_drive_file_placeholder (project root, no parent_id)", flush=True)
    r_file = create_drive_file_placeholder(
        project_id=project_id,
        name=file_name,
        mime_type="application/octet-stream",
        parent_id=None,
    )
    file_id = _object_id(r_file)
    print(f"   file_id={file_id}", flush=True)

    print("2. upload_drive_file_from_path", flush=True)
    r_upload = upload_drive_file_from_path(
        object_id=file_id,
        file_path=str(_FIXTURE),
        content_type="application/octet-stream",
    )
    print(f"   size_bytes={r_upload.get('size_bytes')}", flush=True)

    print("3. rename_drive_object", flush=True)
    r_rename = rename_drive_object(object_id=file_id, new_name=new_name)
    print(json.dumps(r_rename, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
