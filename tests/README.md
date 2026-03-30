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
| `STELLARBRIDGE_TEST_PROJECT_ID` | If set, runs an extra smoke test that calls `drive_list_drive_objects` for this project. |
| `STELLARBRIDGE_HTTP_TIMEOUT` | Seconds for HTTP calls (default `120` in live env). |

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

**What smoke tests do**

- `tools/list` includes expected tool names.
- `projects_list_projects` returns successfully (JSON list).
- If `STELLARBRIDGE_TEST_PROJECT_ID` is set, `drive_list_drive_objects` for that project.

---

## Quick reference

| Goal | Command |
|------|---------|
| Mock MCP integration only | `uv run pytest tests/integration -v` or `task test-integration` |
| Live API (after exporting env) | `uv run pytest tests/integration_live -v` or `task test-integration-live` |
| All tests (live skipped without opt-in) | `uv run pytest` |
