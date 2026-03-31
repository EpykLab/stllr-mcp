#!/usr/bin/env python3
"""Print one transfer id via stdio MCP (same path as live tests).

Use this to set ``STELLARBRIDGE_TEST_TRANSFER_ID`` (e.g. add to ``.env``) instead
of probing the API with raw HTTP.

Loads repo ``.env`` like pytest. Respects optional ``STELLARBRIDGE_TEST_ORG_ID``
the same way as ``live_tool_registry._transfers_list_transfers``.

Usage::

  cd /path/to/stllr-mcp && PYTHONPATH=. uv run python tests/integration_live/print_first_transfer_id.py

Exit 0: prints a single ``tid`` (UUID string) to stdout.
Exit 1: empty list, MCP error, or missing config.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from tests.integration_live.dump_mcp_response_samples import _call_tool
from tests.integration_live.live_tool_registry import LIVE_TOOL_SPECS

_REPO_ROOT = Path(__file__).resolve().parents[2]


async def _main() -> None:
    load_dotenv(_REPO_ROOT / ".env", override=False)
    spec = next(s for s in LIVE_TOOL_SPECS if s.tool_name == "transfers_list_transfers")
    args, skip = spec(_REPO_ROOT)
    if args is None:
        print(skip, file=sys.stderr)
        sys.exit(1)
    data = await _call_tool("transfers_list_transfers", args)
    if isinstance(data, dict) and data.get("_mcp_error"):
        print(json.dumps(data, indent=2), file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, list) or len(data) == 0:
        print(
            "transfers_list_transfers returned no rows; nothing to use as "
            "STELLARBRIDGE_TEST_TRANSFER_ID.",
            file=sys.stderr,
        )
        sys.exit(1)
    tid = data[0].get("tid") if isinstance(data[0], dict) else None
    if not tid:
        print("First row had no tid field.", file=sys.stderr)
        sys.exit(1)
    print(tid)


if __name__ == "__main__":
    asyncio.run(_main())
