# Tests

## Layout

| Path | Purpose |
|------|---------|
| `tests/test_*.py` | Unit tests (mocked HTTP, no MCP subprocess). |
| `tests/integration/` | MCP over **stdio** against a **mock** Stellarbridge API (`pytest-httpserver`). Deterministic; safe for CI. |
| `tests/integration_live/` | MCP over stdio against a **real** API. **Opt-in** only (see below). |
| `tests/fixtures/uploads/` | Committed binary fixtures (e.g. multipart upload E2E). |

Pytest markers: **`integration`** (mock MCP integration), **`live_api`** (real backend).

---

## Unit tests

From the repo root:

```bash
uv run pytest tests/ --ignore=tests/integration --ignore=tests/integration_live
```

Or run everything except live (live tests skip without opt-in env):

```bash
uv run pytest
```

---

## Mock API integration (`tests/integration/`)

These tests spawn `uv run python -m stellarbridge_mcp` and point the server at a local HTTP server that mocks `/api/v1/...` routes. No real Stellarbridge deployment is required.

**What they cover**

- `tools/list` matches the full registered tool surface (`mcp_tool_cases.py`).
- One **`tools/call`** per HTTP-backed tool with expected method/path/query and JSON round-trip.
- Multipart **upload transfer** end-to-end: committed fixture `tests/fixtures/uploads/multipart_upload.bin`, mock API + mock S3 PUT on the same server.
- Optional **LangChain** `create_agent` + fake LLM smoke test (`test_mcp_langgraph_agent.py`).

**Environment**

`tests/integration/conftest.py` sets defaults for the **pytest** process and injects a mock API URL and test key into the **MCP subprocess** (no real credentials).

**Commands**

```bash
uv run pytest tests/integration -v
```

```bash
task test-integration
```

(`task` sets `STELLARBRIDGE_API_KEY` / `STELLARBRIDGE_API_URL` placeholders for the shell; the tests still bind the mock HTTPS server to `STELLARBRIDGE_API_URL` per test.)

---

## Live API integration (`tests/integration_live/`)

Use these to validate the MCP server against a **real** Stellarbridge API (staging, dev stack, etc.). They are **skipped** unless you explicitly opt in.

**Required environment**

| Variable | Meaning |
|----------|---------|
| `STELLARBRIDGE_LIVE_API` | Must be `1`, `true`, `yes`, or `on` to run live tests. |
| `STELLARBRIDGE_API_URL` | API **base URL** only (no `/api/v1` suffix). Must not be the mock placeholder `http://127.0.0.1:9`. |
| `STELLARBRIDGE_API_KEY` | Real API key. Must not be the placeholder `integration-test-api-key`. |

**Optional**

| Variable | Meaning |
|----------|---------|
| `STELLARBRIDGE_HTTP_TIMEOUT` | Seconds for HTTP calls (default `120` in live env). |
| `STELLARBRIDGE_LIVE_ALLOW_MUTATIONS` | Set to `1` / `true` / `yes` / `on` to run tools that create, update, delete, or upload data (see `tests/integration_live/live_tool_registry.py`). |
| `STELLARBRIDGE_TEST_PROJECT_ID` | Project ID for Drive and related tools. |
| `STELLARBRIDGE_TEST_OBJECT_ID` | Drive object ID for get/rename/share/policy tools. |
| `STELLARBRIDGE_TEST_MOVE_PARENT_OBJECT_ID` | Destination folder ID for `drive_move_drive_object` (omit env to move to project root). |
| `STELLARBRIDGE_TEST_DELETE_OBJECT_ID` | Disposable object ID for `drive_delete_drive_object`. |
| `STELLARBRIDGE_TEST_FILE_PLACEHOLDER_OBJECT_ID` | File placeholder for upload/complete URL tools (falls back to `STELLARBRIDGE_TEST_OBJECT_ID`). |
| `STELLARBRIDGE_TEST_DOWNLOAD_OBJECT_ID` | File object for download URL (falls back to `STELLARBRIDGE_TEST_OBJECT_ID`). |
| `STELLARBRIDGE_TEST_POLICY_ID` / `STELLARBRIDGE_TEST_ATTACHMENT_ID` | Policy attach/detach live tests. |
| `STELLARBRIDGE_TEST_TRANSFER_ID` | Transfer id (uuid). If unset, obtain a `tid` from MCP tool **`transfers_list_transfers`** (each row has `tid`), or `task live-first-transfer-id`. |
| `STELLARBRIDGE_TEST_PUBLIC_TRANSFER_ID` | Public transfer id (falls back to `STELLARBRIDGE_TEST_TRANSFER_ID`). |
| `STELLARBRIDGE_TEST_DELETE_TRANSFER_ID` | Disposable transfer for `transfers_delete_transfer`. |
| `STELLARBRIDGE_TEST_ORG_ID` | Optional org filter for `transfers_list_transfers`. |
| `STELLARBRIDGE_TEST_MULTIPART_UPLOAD_ID` / `STELLARBRIDGE_TEST_MULTIPART_FILE_KEY` | IDs from a prior multipart init (presigned URLs / cancel / finalize). |
| `STELLARBRIDGE_TEST_MULTIPART_SIZE_BYTES` / `STELLARBRIDGE_TEST_MULTIPART_FINALIZE_PARTS_JSON` | Finalize multipart: size and JSON array of `{"PartNumber", "ETag"}` parts. |
| `STELLARBRIDGE_LIVE_MULTIPART_FILE_PATH` | Override path for `transfers_upload_transfer_multipart_file` (default: repo fixture `tests/fixtures/uploads/multipart_upload.bin`). |
| `STELLARBRIDGE_TEST_REQUEST_ID` / `STELLARBRIDGE_TEST_DELETE_REQUEST_ID` | File request get/delete. |
| `STELLARBRIDGE_TEST_RECIPIENT_EMAIL` | Email for share/create-request tools. |
| `STELLARBRIDGE_TEST_PARTNER_IDS` | Comma-separated ints for `projects_create_project`. |
| `STELLARBRIDGE_TEST_DELETE_PROJECT_ID` | Disposable empty project for `projects_delete_project`. |
| `STELLARBRIDGE_TEST_ACTOR_ID` | Actor for `audit_get_audit_logs_for_actor`. |
| `STELLARBRIDGE_TEST_AUDIT_FILE_NAME` | Optional override for `audit_get_audit_logs_for_file` (default test name if unset). |

**Commands**

```bash
export STELLARBRIDGE_LIVE_API=1
export STELLARBRIDGE_API_URL='https://your-api-host.example.com'
export STELLARBRIDGE_API_KEY='your-real-api-key'

uv run pytest tests/integration_live -v
```

```bash
task test-integration-live
```

(`task` does not inject URL/key; you must export them in your shell.)

**What live tests do**

- `test_mcp_stdio_live_smoke.py`: `tools/list` returns exactly the tool set in `tests/integration/mcp_tool_cases.py` (`EXPECTED_MCP_TOOL_NAMES`).
- `test_mcp_stdio_live_all_tools.py`: one parametrized `tools/call` per tool; arguments come from `tests/integration_live/live_tool_registry.py` (env-driven). Tools skip with a clear reason when required env or mutation opt-in is missing.

**Resolving `STELLARBRIDGE_TEST_TRANSFER_ID` (MCP only)**

Do not use raw HTTP to scrape a `tid`. From the repo root (loads `.env` like pytest):

```bash
PYTHONPATH=. uv run python tests/integration_live/print_first_transfer_id.py
```

or `task live-first-transfer-id`. Append the printed UUID to `.env` as
`STELLARBRIDGE_TEST_TRANSFER_ID=...`.

---

## Quick reference

| Goal | Command |
|------|---------|
| Mock MCP integration only | `uv run pytest tests/integration -v` or `task test-integration` |
| Live API (after exporting env) | `uv run pytest tests/integration_live -v` or `task test-integration-live` |
| First transfer `tid` via stdio MCP (for env vars) | `task live-first-transfer-id` or `PYTHONPATH=. uv run python tests/integration_live/print_first_transfer_id.py` |
| All tests (live skipped without opt-in) | `uv run pytest` |
