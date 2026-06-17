# Stellarbridge MCP Roadmap

> This is a lightweight, living document. For the latest state, check open issues and PRs at [github.com/EpykLab/stllr-mcp](https://github.com/EpykLab/stllr-mcp).

## Completed

### Tool Surface
- ✅ **Drive upload via local file** (`drive_upload_drive_file_from_path`) — direct upload to object storage via presigned URL
- ✅ **Multipart upload** (`transfers_upload_transfer_multipart_file`) — initialize → presigned PUTs → finalize chain
- ✅ **Drive object management** — create folder, create file placeholder, rename, move (with project root support), delete, get metadata
- ✅ **Transfer operations** — list, get, delete, share, add to Drive, public info
- ✅ **File requests** — create, get status, delete
- ✅ **Projects** — list, create, delete
- ✅ **Audit logs** — query by actor, file, or general filters
- ✅ **Policy listing** — `list_object_policy_attachments` (read-only; mutation tools removed)

### Resilience
- ✅ **Global HTTP 429 retry/backoff** — configurable via `STELLARBRIDGE_HTTP_MAX_RETRIES`, base sleep, max sleep
- ✅ **S3 PUT retry** — multipart upload parts retry on 429/5xx
- ✅ **Safe tid resolution** — best-effort transfer ID lookup after multipart upload via name+size matching

### Testing
- ✅ **Unit tests** — mocked HTTP for all client methods and tool mappings
- ✅ **Mock MCP integration tests** — stdio MCP against local mock API (`pytest-httpserver`)
- ✅ **Live workflow QA runner** — full end-to-end MCP workflow against real API (`run_mcp_live_full_workflow.py`)
- ✅ **Live retest runner** — focused retest for tools that need real backend validation (`run_mcp_live_retest_blocked_tools.py`)
- ✅ **Agent-layer evaluation harness** — planning-only evaluation suite (`agent_layer_test/suite.json`)
- ✅ **CI** — GitHub Actions for unit and integration tests

### Cleanup
- ✅ **Remove policy mutation tools** — `drive_attach_policy_to_object` and `drive_detach_policy_from_object` removed from MCP surface (PR #22)
- ✅ **Retry configuration** — `http_max_retries`, `http_retry_base_sleep_s`, `http_retry_max_sleep_s` in config

## In Progress

- 🔄 **PR #22 review** — cleanup/remove-policy-mutation-tools branch; removing banned policy tools from source, tests, and docs

## Planned

- 📋 **Validate API-side unique transfer names** — upload same filename twice; verify API auto-appends `(1)` and no exact duplicates in `list_transfers`
- 📋 **Fresh end-to-end live validation** — run full workflow runner against current master to confirm all tools pass after recent changes
- 📋 **Clean up obsolete branches** — delete merged `qa/mcp-live-full-workflow-2026-04-08` and reconcile `staging` after PR #22 merge
- 📋 **Review agent evaluation coverage** — ensure removed tools are not referenced in evaluation prompts

## Known Limitations

The following behaviors are expected for API-key auth and are documented as SKIP in live tests:

- `drive_share_drive_object` returns 422 for API-key callers
- `requests_get_file_request` returns 401 (requires upload session)

## Architecture Notes

- **Auth**: `X-API-Key` header; not `Authorization: Bearer`
- **Base URL**: `STELLARBRIDGE_API_URL` (no `/api/v1` suffix)
- **Transfer IDs**: Always use `transfers_list_transfers` to discover `tid`; never guess
- **Safety**: Policy mutations are banned for agents; only read-only `list_object_policy_attachments` is exposed
