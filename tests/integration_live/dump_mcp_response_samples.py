#!/usr/bin/env python3
"""Print JSON returned by MCP tools/call for each live-resolved tool (QA samples).

Loads repo ``.env`` like pytest. Use sanitized output to refresh ``test_tracking.md``.

Usage::

  cd /path/to/stllr-mcp && PYTHONPATH=. uv run python tests/integration_live/dump_mcp_response_samples.py 2>/dev/null

Sanitizes PII and secrets so output is safe to paste into docs. Truncates long arrays
to ``max_list_items`` (default 2). Override: ``MAX_LIST_ITEMS=5``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.integration.mcp_stdio_helpers import json_from_tool_result
from tests.integration_live.live_tool_registry import LIVE_TOOL_SPECS

_REPO_ROOT = Path(__file__).resolve().parents[2]

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _truncate_lists(obj: Any, max_items: int) -> Any:
    if isinstance(obj, list):
        trimmed = obj[:max_items]
        if len(obj) > max_items:
            return [_truncate_lists(x, max_items) for x in trimmed] + [
                f"... {len(obj) - max_items} more items omitted"
            ]
        return [_truncate_lists(x, max_items) for x in trimmed]
    if isinstance(obj, dict):
        return {k: _truncate_lists(v, max_items) for k, v in obj.items()}
    return obj


def _sanitize_pii(obj: Any, _uuid_seq: list[int] | None = None) -> Any:
    """Redact emails, auth subjects, presigned URLs, and long sensitive strings."""
    if _uuid_seq is None:
        _uuid_seq = [0]
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in ("email", "actor") and isinstance(v, str) and _EMAIL.search(v):
                out[k] = "user@example.com"
            elif lk in ("fname", "lname"):
                out[k] = "Redacted"
            elif lk == "domain" and isinstance(v, str):
                out[k] = "partner.example.com"
            elif lk == "filename" and isinstance(v, str):
                out[k] = "redacted-sample" + v[v.rindex(".") :] if "." in v else "redacted"
            elif lk == "name" and isinstance(v, str) and "." in v[-6:]:
                # File-style transfer / document names
                out[k] = "redacted-sample" + v[v.rindex(".") :]
            elif lk == "name" and isinstance(v, str) and len(v) > 24:
                out[k] = v[:12] + "…(redacted)"
            elif lk == "oidc_subject":
                out[k] = "auth0|redacted"
            elif lk == "oidc_issuer" and isinstance(v, str):
                out[k] = "https://tenant.example.auth0.com/"
            elif lk in ("url", "presignedurl", "presigned_url") and isinstance(v, str):
                if v.startswith("http"):
                    out[k] = "<redacted-presigned-url>"
                else:
                    out[k] = _sanitize_pii(v)
            elif lk == "urls" and isinstance(v, list):
                out[k] = [
                    "<redacted-presigned-url>" if isinstance(x, str) and x.startswith("http") else _sanitize_pii(x)
                    for x in v
                ]
            elif isinstance(v, str) and v.startswith("http") and len(v) > 80:
                out[k] = "<redacted-url>"
            else:
                out[k] = _sanitize_pii(v, _uuid_seq)
        return out
    if isinstance(obj, list):
        return [_sanitize_pii(x, _uuid_seq) for x in obj]
    if isinstance(obj, str):
        if _EMAIL.search(obj):
            return _EMAIL.sub("user@example.com", obj)
        if obj.startswith("auth0|"):
            return "auth0|redacted"
        if _UUID.match(obj):
            _uuid_seq[0] += 1
            n = _uuid_seq[0]
            return f"00000000-0000-4000-8000-{n:012d}"
    return obj


def _prepare_sample(data: Any) -> Any:
    max_items = int(os.environ.get("MAX_LIST_ITEMS", "2"))
    return _sanitize_pii(_truncate_lists(data, max_items))


async def _call_tool(name: str, args: dict[str, Any]) -> Any:
    env = {**os.environ}
    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "stellarbridge_mcp"],
        env=env,
        cwd=str(_REPO_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, args)
    if result.isError:
        return {"_mcp_error": True, "content": str(result.content)}
    return json_from_tool_result(name, result.content, is_error=False)


async def main() -> None:
    load_dotenv(_REPO_ROOT / ".env", override=False)
    for spec in LIVE_TOOL_SPECS:
        args, skip = spec(_REPO_ROOT)
        print(f"### {spec.tool_name}")
        if args is None:
            print(f"SKIP: {skip}")
            print()
            continue
        try:
            data = await _call_tool(spec.tool_name, args)
            safe = _prepare_sample(data)
            print(json.dumps(safe, indent=2))
        except Exception as e:
            print(f"ERROR: {e!r}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
